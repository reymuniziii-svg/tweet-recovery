"""Stage 1 — Discover: CDX queries -> manifest of unique tweet IDs + pages.

Queries every host variant Twitter has lived on, extracts tweet IDs from
capture URLs, groups captures per ID (each capture is a retry candidate
for the extract stage), and filters to the requested date range using
snowflake-decoded dates. Also discovers captures of the profile/timeline
page itself (feed "page views"), which each show the ~20 most recent
tweets and the account's retweets.
"""

import json
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from lib.cdx import CdxClient
from lib.snowflake import capture_ts_to_datetime, snowflake_to_datetime

# CDX canonicalizes www.* into the bare host, so twitter.com already
# covers www.twitter.com — querying both returns identical rows twice.
HOSTS = ["twitter.com", "mobile.twitter.com", "x.com"]
STATUS_RE = re.compile(r"/status(?:es)?/(\d{6,25})")

# Extract tries captures 200s-first / oldest-first; keep a bounded set.
MAX_CAPTURES_STORED = 8

# A page capture shortly after --to can still show in-range tweets.
PAGE_DATE_GRACE = timedelta(days=30)

# Query-string params that select different timeline content (older pages);
# everything else (?lang=, tracking params) is a duplicate of the bare page.
PAGINATION_PARAMS = {"page", "max_id", "since_id"}


def _page_re(handle: str):
    """Timeline-page URLs for this handle: bare profile, /with_replies,
    and their query-string variants. Rejects /status/..., non-timeline
    paths (/media, /followers, ...), and prefix-colliding other handles
    (CDX prefix queries match jack* -> jackson)."""
    h = re.escape(handle)
    return re.compile(
        rf"^https?://(?:www\.)?(?:mobile\.)?(?:twitter|x)\.com/{h}"
        rf"(?:/with_replies)?/?(?:\?[^#]*)?$",
        re.IGNORECASE,
    )


def discover(handle: str, workdir: Path, date_from=None, date_to=None, throttle=1.5,
             include_pages=True, max_page_captures=400):
    """Run CDX discovery and write work/<handle>/manifest.json. Returns the manifest."""
    cdx = CdxClient(throttle=throttle)
    captures_by_id = {}
    raw_captures = 0

    for host in HOSTS:
        pattern = f"{host}/{handle}/status*"
        count_before = raw_captures
        for row in cdx.query(pattern):
            raw_captures += 1
            m = STATUS_RE.search(row["original"])
            if not m:
                continue
            tid = int(m.group(1))
            captures_by_id.setdefault(tid, []).append(row)
        print(f"  [discover] {pattern}: {raw_captures - count_before} captures")

    raw_page_captures = 0
    pages = []
    if include_pages:
        page_re = _page_re(handle)
        page_rows = []
        for host in HOSTS:
            pattern = f"{host}/{handle}*"
            count_before = raw_page_captures
            # Server-side filter strips the /status/ bulk — an optimization
            # only; the client-side regex below is the source of truth.
            extra = {"filter": ["!original:.*/status(es)?/.*"]}
            for row in cdx.query(pattern, extra_params=extra):
                if not page_re.match(row["original"]):
                    continue
                raw_page_captures += 1
                page_rows.append(row)
            print(f"  [discover] {pattern}: {raw_page_captures - count_before} page captures")
        pages = _select_pages(page_rows, date_from, date_to, max_page_captures)

    tweets = {}
    for tid, caps in captures_by_id.items():
        dt = snowflake_to_datetime(tid) or capture_ts_to_datetime(
            min(c["timestamp"] for c in caps)
        )
        if date_from and dt.date() < date_from:
            continue
        if date_to and dt.date() > date_to:
            continue
        # 200s first, then oldest first (older captures are more likely
        # server-rendered); everything else afterwards as a last resort.
        caps.sort(key=lambda c: (c.get("statuscode") != "200", c["timestamp"]))
        tweets[str(tid)] = {
            "total_captures": len(caps),
            "captures": [
                {"timestamp": c["timestamp"], "original": c["original"],
                 "statuscode": c.get("statuscode", "")}
                for c in caps[:MAX_CAPTURES_STORED]
            ],
        }

    manifest = {
        "handle": handle,
        "raw_captures": raw_captures,
        "unique_ids": len(tweets),
        "tweets": tweets,
        "raw_page_captures": raw_page_captures,
        "page_captures_selected": len(pages),
        "pages": pages,
    }
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "manifest.json").write_text(json.dumps(manifest))
    print(f"  [discover] {raw_captures} raw captures -> {len(tweets)} unique tweet IDs in range")
    if include_pages:
        print(f"  [discover] {raw_page_captures} page captures -> {len(pages)} selected")
    return manifest


def _select_pages(page_rows, date_from, date_to, max_page_captures):
    """Date-filter, dedupe per (day, variant), and evenly sample page captures."""
    grace_to = None
    if date_to:
        grace_to = date_to + PAGE_DATE_GRACE

    buckets = {}
    for row in page_rows:
        day = capture_ts_to_datetime(row["timestamp"]).date()
        # Everything a page shows predates its capture, so captures before
        # --from are useless; a little after --to can still be in range
        # (the per-tweet date filter in extract_pages is authoritative).
        if date_from and day < date_from:
            continue
        if grace_to and day > grace_to:
            continue
        split = urlsplit(row["original"])
        variant = "with_replies" if "/with_replies" in split.path.lower() else ""
        pagination = sorted(
            (k, v) for k, v in parse_qsl(split.query) if k.lower() in PAGINATION_PARAMS
        )
        key = (day, variant, tuple(pagination))
        cur = buckets.get(key)
        # Within a bucket keep one capture: 200s first, then earliest
        # (mirrors the per-tweet capture sort — older = more likely SSR).
        rank = (row.get("statuscode") != "200", row["timestamp"])
        if cur is None or rank < (cur.get("statuscode") != "200", cur["timestamp"]):
            buckets[key] = row

    selected = sorted(buckets.values(), key=lambda r: r["timestamp"])
    if max_page_captures and len(selected) > max_page_captures:
        # Even temporal sampling, not truncation, to preserve coverage spread.
        step = len(selected) / max_page_captures
        selected = [selected[int(i * step)] for i in range(max_page_captures)]

    return [
        {"timestamp": r["timestamp"], "original": r["original"],
         "statuscode": r.get("statuscode", "")}
        for r in selected
    ]
