"""Stage 2 — Extract: fetch raw snapshots, run the parser cascade.

Per tweet ID, tries capture candidates in manifest order (200s first,
oldest first) until one yields verbatim text. Results append to
recovered.jsonl / failed.jsonl as they complete, so interrupted runs
resume by skipping IDs already present in either file.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from lib.parsers import extract_tweet_text
from lib.snowflake import capture_ts_to_datetime, snowflake_to_datetime

USER_AGENT = "tweet-recovery/1.0 (archival research tool; contact: repo operator)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class _Throttle:
    """Global minimum spacing between requests across worker threads."""

    def __init__(self, interval: float):
        self.interval = interval
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = self.last + self.interval - now
            self.last = max(now, self.last + self.interval)
        if delay > 0:
            time.sleep(delay)


def _polite_get(session, url, throttle, max_retries=4):
    """GET with throttle + backoff. Returns Response or None on network failure."""
    for attempt in range(max_retries):
        throttle.wait()
        try:
            resp = session.get(url, timeout=30, allow_redirects=True)
        except requests.RequestException:
            time.sleep(min(2 ** attempt * 2, 30))
            continue
        if resp.status_code in RETRY_STATUSES:
            retry_after = resp.headers.get("Retry-After")
            try:
                time.sleep(min(float(retry_after), 120))
            except (TypeError, ValueError):
                time.sleep(min(2 ** attempt * 3, 60))
            continue
        return resp
    return None


def _process_one(tid: str, entry: dict, session, throttle, max_captures: int):
    """Try captures until text is found. Returns ('recovered'|'failed', record)."""
    tweet_id = int(tid)
    attempted = []
    saw_html_shell = False
    saw_fetch_failure = False

    for cap in entry["captures"][:max_captures]:
        ts, original = cap["timestamp"], cap["original"]
        attempted.append(ts)
        archive_url = f"https://web.archive.org/web/{ts}id_/{original}"
        resp = _polite_get(session, archive_url, throttle)
        if resp is None:
            saw_fetch_failure = True
            continue
        if resp.status_code != 200 or not resp.text:
            continue
        text, method = extract_tweet_text(resp.text)
        if not text:
            saw_html_shell = True
            continue

        capture_dt = capture_ts_to_datetime(ts)
        snowflake_dt = snowflake_to_datetime(tweet_id)
        if snowflake_dt and snowflake_dt <= capture_dt:
            date, confidence = snowflake_dt, "exact"
        else:
            # Pre-snowflake ID (or clock-impossible decode): date the tweet
            # by its earliest capture instead.
            date, confidence = capture_dt, "approximate"

        host = original.split("/")[2].lower().removeprefix("www.")
        return "recovered", {
            "tweet_id": tid,
            "date": date.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "date_confidence": confidence,
            "source": host,
            "archive_url": archive_url,
            "capture_timestamp": ts,
            "method": method,
        }

    if saw_html_shell:
        reason, needs_browser = "JS shell, no og:description", True
    elif saw_fetch_failure:
        reason, needs_browser = "fetch failed", False
    else:
        reason, needs_browser = "all captures 404", False
    first = entry["captures"][0]["original"] if entry["captures"] else ""
    return "failed", {
        "tweet_id": tid,
        "reason": reason,
        "needs_browser": needs_browser,
        "attempted_captures": ",".join(attempted),
        "original_url": first,
    }


def _load_done_ids(workdir: Path):
    done = set()
    for name in ("recovered.jsonl", "failed.jsonl"):
        path = workdir / name
        if path.exists():
            with path.open() as f:
                for line in f:
                    if line.strip():
                        done.add(json.loads(line)["tweet_id"])
    return done


def extract(manifest: dict, workdir: Path, workers=3, max_captures=4, throttle_s=0.6):
    """Run extraction over the manifest; append-resume via the jsonl files."""
    done = _load_done_ids(workdir)
    todo = {tid: e for tid, e in manifest["tweets"].items() if tid not in done}
    total = len(manifest["tweets"])
    print(f"  [extract] {total} IDs total, {len(done)} already done, {len(todo)} to fetch")
    if not todo:
        return

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    throttle = _Throttle(throttle_s)
    write_lock = threading.Lock()
    counts = {"recovered": 0, "failed": 0}

    with (workdir / "recovered.jsonl").open("a") as rec_f, \
         (workdir / "failed.jsonl").open("a") as fail_f, \
         ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_one, tid, entry, session, throttle, max_captures): tid
            for tid, entry in todo.items()
        }
        for i, fut in enumerate(as_completed(futures), 1):
            status, record = fut.result()
            out = rec_f if status == "recovered" else fail_f
            with write_lock:
                out.write(json.dumps(record) + "\n")
                out.flush()
            counts[status] += 1
            if i % 50 == 0 or i == len(futures):
                print(f"  [extract] {i}/{len(futures)} "
                      f"(recovered {counts['recovered']}, failed {counts['failed']})")
