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

from bs4 import BeautifulSoup

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
        # Hidden URL-expansion helpers duplicate link text; drop them.
        for junk in el.select(".tco-ellipsis, .invisible"):
            junk.decompose()
        text = _clean(el.get_text())
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


def _clean(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _strip_wrapping_quotes(s: str) -> str:
    for opener, closer in _WRAPPING_QUOTES:
        if len(s) >= 2 and s.startswith(opener) and s.endswith(closer):
            return s[1:-1].strip()
    return s
