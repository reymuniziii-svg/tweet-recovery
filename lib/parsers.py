"""Tweet-text extraction from archived Twitter HTML.

Cascade (verbatim text only — nothing inferred, nothing fabricated):
  1. Legacy server-rendered markup: the `.tweet-text` element. Permalink
     pages can include ancestor/reply tweets, so prefer the one inside
     `.permalink-tweet` (the page's main tweet).
  2. `og:description` / `twitter:description` meta tag — modern captures
     where Twitter still served SSR metadata for crawlers. Twitter wraps
     the text in curly quotes; strip exactly one wrapping pair.
  3. No text found -> caller records an honest failure (JS app shell).
"""

import html
import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Some captures are XML (RSS/redirect stubs); the HTML parser handles them fine.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_WS = re.compile(r"\s+")

# One wrapping pair of straight/curly quotes around the whole text.
_WRAPPING_QUOTES = [("“", "”"), ('"', '"'), ("„", "“")]


def extract_tweet_text(raw_html: str):
    """Return (text, method) or (None, None)."""
    soup = BeautifulSoup(raw_html, "lxml")

    # 1) Legacy server-rendered tweet text
    el = soup.select_one(".permalink-tweet .tweet-text") or soup.select_one(
        ".permalink-tweet .js-tweet-text"
    )
    if el is None:
        # mobile.twitter.com legacy pages and non-permalink layouts
        el = soup.select_one(".tweet-text") or soup.select_one(".js-tweet-text")
    if el is not None:
        text = _text_from_tweet_el(el)
        if text:
            return text, "tweet-text"

    # 2) og:description / twitter:description
    for key in ("og:description", "twitter:description"):
        meta = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        content = meta.get("content") if meta else None
        if content:
            text = _strip_wrapping_quotes(_clean(html.unescape(content)))
            if text:
                return text, "og:description"

    return None, None


def _text_from_tweet_el(el) -> str:
    # Legacy markup ellipsizes link display text (t.co wrappers); the
    # full destination lives in data-expanded-url. Substitute it so
    # URLs come out complete instead of truncated.
    for a in el.find_all("a"):
        expanded = a.get("data-expanded-url")
        if expanded:
            a.replace_with(expanded)
    # Remaining hidden helpers (media links etc.) duplicate text; drop.
    for junk in el.select(".tco-ellipsis, .invisible"):
        junk.decompose()
    return _clean(el.get_text())


_STATUS_HREF_RE = re.compile(r"/status(?:es)?/(\d{6,25})")
_CLASSIC_RT_RE = re.compile(r"^RT @(\w+)")


def extract_timeline_tweets(raw_html: str, handle: str):
    """Parse a profile/timeline page capture into its visible tweets.

    Returns (tweets, method) where tweets is a list of dicts:
      {tweet_id, retweet_id, screen_name, text, is_retweet, retweeted_user}
    or ([], None) when no server-rendered timeline markup is present.

    og:description is never used here — on a profile page it is the
    account bio, not tweet text.
    """
    soup = BeautifulSoup(raw_html, "lxml")
    handle = handle.lower()

    tweets = _parse_stream_items(soup, handle)
    if tweets:
        return tweets, "stream-item"

    tweets = _parse_mobile_tweets(soup, handle)
    if tweets:
        return tweets, "mobile-tweet"

    tweets = _parse_status_lis(soup, handle)
    if tweets:
        return tweets, "status-li"

    return [], None


def _parse_stream_items(soup, handle):
    """Desktop stream markup, ~2011-2019: div.tweet[data-tweet-id]."""
    tweets, seen = [], set()
    for el in soup.select("div[data-tweet-id]"):
        tid = el.get("data-tweet-id", "")
        if not tid.isdigit():
            continue
        retweet_id = el.get("data-retweet-id") or None
        if (tid, retweet_id) in seen:
            continue
        seen.add((tid, retweet_id))

        screen_name = el.get("data-screen-name", "").lower()
        is_retweet = bool(retweet_id) or el.select_one(".js-retweet-text") is not None
        # Profile timelines can inline other users' tweets (conversation
        # modules); the only intentional other-user content is a retweet.
        if not is_retweet and screen_name and screen_name != handle:
            continue

        text_el = el.select_one(".tweet-text") or el.select_one(".js-tweet-text")
        text = _text_from_tweet_el(text_el) if text_el else ""
        tweets.append({
            "tweet_id": tid,
            "retweet_id": retweet_id,
            "screen_name": screen_name,
            "text": text,
            "is_retweet": is_retweet,
            "retweeted_user": screen_name if is_retweet else None,
        })
    return tweets


def _parse_mobile_tweets(soup, handle):
    """mobile.twitter.com legacy markup, ~2012-2019: table.tweet."""
    tweets, seen = [], set()
    for el in soup.select("table.tweet"):
        tid = None
        text_el = el.select_one(".tweet-text")
        if text_el is not None and str(text_el.get("data-id", "")).isdigit():
            tid = text_el["data-id"]
        if tid is None:
            href = el.get("href") or ""
            link = el.select_one('a[href*="/status/"], a[href*="/statuses/"]')
            if link is not None:
                href = link.get("href", "")
            m = _STATUS_HREF_RE.search(href)
            if m:
                tid = m.group(1)
        if tid is None or tid in seen:
            continue
        seen.add(tid)

        username_el = el.select_one(".username")
        screen_name = _clean(username_el.get_text()).lstrip("@").lower() if username_el else ""
        context = el.select_one(".tweet-social-context")
        is_retweet = context is not None and "retweet" in context.get_text().lower()
        if not is_retweet and screen_name and screen_name != handle:
            continue

        body = (text_el.select_one(".dir-ltr") if text_el else None) or text_el
        text = _text_from_tweet_el(body) if body else ""
        tweets.append({
            "tweet_id": tid,
            "retweet_id": None,
            "screen_name": screen_name,
            "text": text,
            "is_retweet": is_retweet,
            "retweeted_user": screen_name if is_retweet else None,
        })
    return tweets


def _parse_status_lis(soup, handle):
    """Desktop ~2008-2010 markup: table#timeline tr[id^=status_] (earlier)
    or ol#timeline li[id^=status_] (later), text in span.entry-content.

    Everything on the profile page is the handle's own tweet; classic
    retweets are the handle's own "RT @user: ..." tweets — text kept
    verbatim, flagged is_retweet with the quoted author.
    """
    tweets, seen = [], set()
    for el in soup.select('li[id^="status_"], tr[id^="status_"]'):
        m = re.match(r"status_(\d+)$", el.get("id", ""))
        if not m or m.group(1) in seen:
            continue
        text_el = el.select_one("span.entry-content")
        if text_el is None:
            continue
        seen.add(m.group(1))
        text = _text_from_tweet_el(text_el)
        rt = _CLASSIC_RT_RE.match(text)
        tweets.append({
            "tweet_id": m.group(1),
            "retweet_id": None,
            "screen_name": handle,
            "text": text,
            "is_retweet": rt is not None,
            "retweeted_user": rt.group(1) if rt else None,
        })
    return tweets


def _clean(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _strip_wrapping_quotes(s: str) -> str:
    for opener, closer in _WRAPPING_QUOTES:
        if len(s) >= 2 and s.startswith(opener) and s.endswith(closer):
            return s[1:-1].strip()
    return s
