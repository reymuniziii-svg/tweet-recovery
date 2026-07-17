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
- The pipeline mines **two archive sources**: captures of individual tweet
  URLs, and captures of the profile **feed page itself** (which also surface
  the account's **retweets**). `--no-pages` disables the feed-page source;
  `--max-page-captures` (default 400) bounds how many feed captures are
  fetched after per-day dedup and even time-sampling.
- Runs are **resumable**: if interrupted, re-run the same command — completed
  tweet IDs and feed captures are skipped. Add `--skip-discover` to also
  reuse the CDX manifest.
- Large accounts take a while (~0.6s per snapshot fetch, a few thousand
  fetches is normal). Run it in the background and check progress from the
  printed `[pages] N/M` and `[extract] N/M` lines.

## Integrity rules (non-negotiable)

- Every tweet text is **verbatim from an archived snapshot**. The tool never
  infers, reconstructs, or fabricates text — and neither do you. Missing
  tweets stay missing and are listed honestly on the Failed sheet.
- Never edit recovered text beyond what the deliverable format requires.
- Always deliver the Summary numbers (recovery rate, failure breakdown) with
  the sheet. Undercounting caveats is misrepresentation.

## QA protocol before delivering

1. Open `tweets.csv`, pick 5 random rows (include at least one
   `Recovered Via = timeline` row if any exist), and fetch each row's
   **Archive URL**. Confirm the text matches the snapshot verbatim — for
   timeline rows the snapshot is a feed page, so find the tweet among the
   ~20 shown. If any mismatch: stop and investigate `lib/parsers.py` — do
   not deliver.
2. Sanity-check the Summary sheet: recovery rate, date range, failure counts.
3. Spot-check that dates look sane (no tweets dated after their capture).
4. For retweet rows (`Is Retweet = True`): the text belongs to
   **Retweeted User**, not the account — confirm the attribution reads
   correctly in the deliverable.

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
- **`Recovered Via = timeline`**: the text came from an archived capture of
  the profile feed page rather than the tweet's own URL — same verbatim
  standard, and the Archive URL points at that feed capture.
- **Retweets** only come from feed captures. They're dated by the retweet's
  own ID when the markup carries one (`exact` = when the account retweeted);
  older markup has no retweet ID, so those rows are `approximate`
  (capture-dated) and their Tweet ID reads `rt:<original id>`.
- **`timeline item, no text`** (Failed sheet): a feed capture showed the
  tweet existed but carried no extractable text, and the tweet has no
  individual-URL captures either.

## When Wayback coverage is thin

See [docs/sources.md](docs/sources.md) for gap-fillers: archive.today,
Politwoops (deleted tweets of US politicians), the Archive Team Twitter
stream, and the Memento aggregator. These are manual/supplementary — the
pipeline only automates Wayback.

## Layout

- `recover.py` — CLI orchestrator (discover → extract pages → extract → report)
- `stages/` — the four pipeline stages
- `lib/` — CDX client, polite HTTP fetching, snowflake decoding, HTML parsers
- `tests/` — parser/selection tests against real saved Wayback captures
- `work/<handle>/` — manifest + append-only results (resume state; safe to
  delete to force a fresh run)
- `out/<handle>/` — deliverables
