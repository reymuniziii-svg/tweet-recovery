"""Stage 2a — Extract pages: mine profile/timeline captures for tweets.

Each server-rendered timeline capture shows the ~20 most recent tweets
(including retweets, which the per-tweet pipeline never sees). Runs
before the per-ID extract stage: everything recovered here is skipped
there, saving one fetch per tweet.

Results append to recovered.jsonl in the same schema as the per-ID stage
(plus recovered_via/is_retweet/retweeted_user); processed page captures
append to pages_done.jsonl so interrupted runs resume.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from lib.fetch import Throttle, polite_get, USER_AGENT
from lib.parsers import extract_timeline_tweets
from lib.snowflake import capture_ts_to_datetime, snowflake_to_datetime


def _process_page(cap: dict, handle: str, session, throttle):
    """Fetch and parse one page capture. Returns (status, tweets, method)."""
    ts, original = cap["timestamp"], cap["original"]
    archive_url = f"https://web.archive.org/web/{ts}id_/{original}"
    resp = polite_get(session, archive_url, throttle)
    if resp is None:
        return "fetch_failed", [], None
    if resp.status_code != 200 or not resp.text:
        return "http_error", [], None
    tweets, method = extract_timeline_tweets(resp.text, handle)
    if not tweets:
        if "react-root" in resp.text or "data-reactroot" in resp.text:
            return "js_shell", [], None
        return "no_tweets", [], None
    return "parsed", tweets, method


def _tweet_record(tweet: dict, cap: dict, method: str):
    """Build a recovered.jsonl record (same schema as the per-ID stage).

    Returns (row_id, record). Row identity: own tweet -> its ID; retweet
    with a retweet ID -> that ID (the retweet event's own snowflake);
    retweet without one (older markup) -> "rt:<original id>" (non-numeric,
    kept out of failed.jsonl whose report sort is int-based).
    """
    ts, original = cap["timestamp"], cap["original"]
    capture_dt = capture_ts_to_datetime(ts)

    if tweet["is_retweet"]:
        if tweet["retweet_id"]:
            row_id = tweet["retweet_id"]
            # The retweet's own snowflake = when the handle retweeted.
            snowflake_dt = snowflake_to_datetime(int(row_id))
        else:
            row_id = f"rt:{tweet['tweet_id']}"
            # The original's snowflake dates the original tweet, not the
            # retweeting act — never use it; fall back to capture time.
            snowflake_dt = None
    else:
        row_id = tweet["tweet_id"]
        snowflake_dt = snowflake_to_datetime(int(row_id))

    if snowflake_dt and snowflake_dt <= capture_dt:
        date, confidence = snowflake_dt, "exact"
    else:
        date, confidence = capture_dt, "approximate"

    host = original.split("/")[2].lower().removeprefix("www.")
    record = {
        "tweet_id": row_id,
        "date": date.strftime("%Y-%m-%d %H:%M:%S"),
        "text": tweet["text"],
        "date_confidence": confidence,
        "source": host,
        "archive_url": f"https://web.archive.org/web/{ts}id_/{original}",
        "capture_timestamp": ts,
        "method": method,
        "recovered_via": "timeline",
        "is_retweet": tweet["is_retweet"],
        "retweeted_user": tweet["retweeted_user"],
    }
    if tweet["is_retweet"]:
        record["retweet_of"] = tweet["tweet_id"]
    return row_id, record


def _load_done_pages(workdir: Path):
    done = set()
    path = workdir / "pages_done.jsonl"
    if path.exists():
        with path.open() as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    done.add(f"{rec['timestamp']} {rec['original']}")
    return done


def _load_recovered_ids(workdir: Path):
    # recovered.jsonl only — a tweet that previously *failed* (JS shell)
    # must still be recoverable from a timeline page.
    done = set()
    path = workdir / "recovered.jsonl"
    if path.exists():
        with path.open() as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["tweet_id"])
    return done


def extract_pages(manifest: dict, workdir: Path, workers=3, throttle_s=0.6,
                  date_from=None, date_to=None):
    """Mine timeline page captures; append-resume via jsonl files."""
    handle = manifest["handle"]
    done_pages = _load_done_pages(workdir)
    todo = [
        cap for cap in manifest.get("pages", [])
        if f"{cap['timestamp']} {cap['original']}" not in done_pages
    ]
    total = len(manifest.get("pages", []))
    print(f"  [pages] {total} page captures, {total - len(todo)} already done, "
          f"{len(todo)} to fetch")
    if not todo:
        return

    seen = _load_recovered_ids(workdir)
    manifest_ids = set(manifest["tweets"])
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    throttle = Throttle(throttle_s)
    write_lock = threading.Lock()
    counts = {"parsed": 0, "js_shell": 0, "http_error": 0,
              "fetch_failed": 0, "no_tweets": 0}
    new_tweets_total = 0
    # (tid, capture ts, page original) for numeric-ID items with no text;
    # written to failed.jsonl after the pool drains if still unrecovered.
    no_text = []

    workdir.mkdir(parents=True, exist_ok=True)
    with (workdir / "recovered.jsonl").open("a") as rec_f, \
         (workdir / "pages_done.jsonl").open("a") as page_f, \
         ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_page, cap, handle, session, throttle): cap
            for cap in todo
        }
        for i, fut in enumerate(as_completed(futures), 1):
            cap = futures[fut]
            status, tweets, method = fut.result()
            counts[status] += 1
            new_count = 0
            with write_lock:
                for tweet in tweets:
                    row_id, record = _tweet_record(tweet, cap, method)
                    if row_id in seen:
                        continue
                    if not tweet["text"]:
                        if tweet["tweet_id"].isdigit() and tweet["tweet_id"] not in manifest_ids:
                            no_text.append((tweet["tweet_id"], cap["timestamp"],
                                            cap["original"]))
                        continue
                    row_date = record["date"][:10]
                    if date_from and row_date < date_from.isoformat():
                        continue
                    if date_to and row_date > date_to.isoformat():
                        continue
                    # Truncated timeline text with a permalink capture
                    # available: defer to the per-ID pass for full text.
                    if (not tweet["is_retweet"] and tweet["text"].endswith("…")
                            and row_id in manifest_ids):
                        continue
                    seen.add(row_id)
                    rec_f.write(json.dumps(record) + "\n")
                    new_count += 1
                # Tweets first, page-done line last: a crash in between
                # replays the page, and per-tweet dedup drops duplicates.
                rec_f.flush()
                page_f.write(json.dumps({
                    "timestamp": cap["timestamp"], "original": cap["original"],
                    "status": status, "tweets_found": len(tweets),
                    "new_tweets": new_count,
                }) + "\n")
                page_f.flush()
            new_tweets_total += new_count
            if i % 25 == 0 or i == len(futures):
                print(f"  [pages] {i}/{len(futures)} "
                      f"(tweets recovered {new_tweets_total}, JS shells {counts['js_shell']})")

    already_failed = set()
    failed_path = workdir / "failed.jsonl"
    if failed_path.exists():
        with failed_path.open() as f:
            for line in f:
                if line.strip():
                    already_failed.add(json.loads(line)["tweet_id"])
    still_missing = {
        tid: (ts, original) for tid, ts, original in no_text
        if tid not in seen and tid not in already_failed
    }
    if still_missing:
        with failed_path.open("a") as fail_f:
            for tid, (ts, original) in still_missing.items():
                fail_f.write(json.dumps({
                    "tweet_id": tid,
                    "reason": "timeline item, no text",
                    "needs_browser": False,
                    "attempted_captures": ts,
                    "original_url": original,
                }) + "\n")
            fail_f.flush()

    print(f"  [pages] done: {new_tweets_total} tweets from timeline pages "
          f"({counts['parsed']} parsed, {counts['js_shell']} JS shell, "
          f"{counts['no_tweets']} no tweets, {counts['http_error']} http errors, "
          f"{counts['fetch_failed']} fetch failures)")
