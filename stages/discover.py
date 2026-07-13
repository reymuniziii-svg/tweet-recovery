"""Stage 1 — Discover: CDX queries -> manifest of unique tweet IDs.

Queries every host variant Twitter has lived on, extracts tweet IDs from
capture URLs, groups captures per ID (each capture is a retry candidate
for the extract stage), and filters to the requested date range using
snowflake-decoded dates.
"""

import json
import re
from pathlib import Path

from lib.cdx import CdxClient
from lib.snowflake import capture_ts_to_datetime, snowflake_to_datetime

HOSTS = ["twitter.com", "www.twitter.com", "mobile.twitter.com", "x.com"]
STATUS_RE = re.compile(r"/status(?:es)?/(\d{6,25})")

# Extract tries captures 200s-first / oldest-first; keep a bounded set.
MAX_CAPTURES_STORED = 8


def discover(handle: str, workdir: Path, date_from=None, date_to=None, throttle=1.5):
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
    }
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "manifest.json").write_text(json.dumps(manifest))
    print(f"  [discover] {raw_captures} raw captures -> {len(tweets)} unique tweet IDs in range")
    return manifest
