# Agent Playbook — tweet-recovery

You are operating a tool that recovers a Twitter/X account's old tweets from
the Internet Archive's Wayback Machine and delivers them as a clean
spreadsheet. The operator hands you a **handle** and optionally a **time
range**; you run the pipeline, QA the output, and deliver.

## The one command

```bash
pip install -r requirements.txt   # first run only
python recover.py --handle <name> --from 2016-01-01 --to 2024-12-31
```

- `--from` / `--to` are optional; omit for the account's full archived history.
- Output lands in `out/<handle>/`: an `.xlsx` (Tweets / Failed / Summary
  sheets) plus flat `tweets.csv` and `failed.csv`.
- Runs are **resumable**: if interrupted, re-run the same command — completed
  tweet IDs are skipped. Add `--skip-discover` to also reuse the CDX manifest.
- Large accounts take a while (~0.6s per snapshot fetch, a few thousand
  fetches is normal). Run it in the background and check progress from the
  printed `[extract] N/M` lines.

## Integrity rules (non-negotiable)

- Every tweet text is **verbatim from an archived snapshot**. The tool never
  infers, reconstructs, or fabricates text — and neither do you. Missing
  tweets stay missing and are listed honestly on the Failed sheet.
- Never edit recovered text beyond what the deliverable format requires.
- Always deliver the Summary numbers (recovery rate, failure breakdown) with
  the sheet. Undercounting caveats is misrepresentation.

## QA protocol before delivering

1. Open `tweets.csv`, pick 5 random rows, and fetch each row's **Archive URL**.
   Confirm the text matches the snapshot verbatim. If any mismatch: stop and
   investigate `lib/parsers.py` — do not deliver.
2. Sanity-check the Summary sheet: recovery rate, date range, failure counts.
3. Spot-check that dates look sane (no tweets dated after their capture).

## Interpreting results

- **Expected recovery rates:** ~85–92% for accounts whose activity is mostly
  pre-2020. Lower for newer accounts — around 2020 Twitter switched to a
  client-side JS app, so later captures are often empty "JS shells" with no
  server-rendered text.
- **`JS shell, no og:description`** (Failed sheet): the archive has the page
  but it's an unrendered app shell. `Needs Browser = True` marks these as
  candidates for a future headless-render pass (not built yet).
- **`all captures 404`**: the archive indexed the URL but every capture
  returns 404. Genuinely unrecoverable from Wayback.
- **`fetch failed`**: network trouble during the run — re-run the command;
  resume will retry only these after you delete their lines from
  `work/<handle>/failed.jsonl`.
- **Date Confidence `exact`** = decoded from the tweet ID (snowflake), to the
  second. `approximate` = pre-2010 tweet dated by its earliest capture.

## When Wayback coverage is thin

See [docs/sources.md](docs/sources.md) for gap-fillers: archive.today,
Politwoops (deleted tweets of US politicians), the Archive Team Twitter
stream, and the Memento aggregator. These are manual/supplementary — the
pipeline only automates Wayback.

## Layout

- `recover.py` — CLI orchestrator (discover → extract → report)
- `stages/` — the three pipeline stages
- `lib/` — CDX client, snowflake decoding, HTML parsers
- `work/<handle>/` — manifest + append-only results (resume state; safe to
  delete to force a fresh run)
- `out/<handle>/` — deliverables
