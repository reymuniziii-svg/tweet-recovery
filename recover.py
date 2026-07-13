#!/usr/bin/env python3
"""Recover a Twitter/X account's archived tweets from the Wayback Machine.

    python recover.py --handle <handle> --from 2016-01-01 --to 2024-12-31

Pipeline: discover (CDX index) -> extract (raw snapshots + parser cascade)
-> report (xlsx + CSVs). Interrupted runs resume automatically; re-run the
same command and completed IDs are skipped.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stages.build_sheet import build_sheet
from stages.discover import discover
from stages.extract import extract


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--handle", required=True, help="Twitter/X handle (with or without @)")
    ap.add_argument("--from", dest="date_from", type=parse_date, default=None,
                    help="Earliest tweet date, YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", type=parse_date, default=None,
                    help="Latest tweet date, YYYY-MM-DD")
    ap.add_argument("--out", default=None, help="Output directory (default out/<handle>)")
    ap.add_argument("--workers", type=int, default=3, help="Concurrent fetches (default 3)")
    ap.add_argument("--max-captures", type=int, default=4,
                    help="Capture candidates to try per tweet (default 4)")
    ap.add_argument("--throttle", type=float, default=0.6,
                    help="Min seconds between snapshot fetches (default 0.6)")
    ap.add_argument("--skip-discover", action="store_true",
                    help="Reuse the existing manifest instead of re-querying CDX")
    args = ap.parse_args()

    handle = args.handle.lstrip("@").lower()
    root = Path(__file__).parent
    workdir = root / "work" / handle
    outdir = Path(args.out) if args.out else root / "out" / handle

    print(f"[recover] @{handle}"
          + (f" from {args.date_from}" if args.date_from else "")
          + (f" to {args.date_to}" if args.date_to else ""))

    manifest_path = workdir / "manifest.json"
    if args.skip_discover and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        print(f"[recover] reusing manifest: {manifest['unique_ids']} IDs")
    else:
        manifest = discover(handle, workdir, args.date_from, args.date_to)
    if not manifest["tweets"]:
        print("[recover] nothing found in the archive for this handle/range.")
        return

    extract(manifest, workdir, workers=args.workers,
            max_captures=args.max_captures, throttle_s=args.throttle)

    xlsx = build_sheet(handle, workdir, outdir,
                       raw_captures=manifest["raw_captures"],
                       unique_ids=manifest["unique_ids"])
    print(f"[recover] done -> {xlsx}")
    print(f"[recover]        {outdir / 'tweets.csv'}")
    print(f"[recover]        {outdir / 'failed.csv'}")


if __name__ == "__main__":
    main()
