# tweet-recovery

Recover a Twitter/X account's old tweets — including deleted ones — from the
Internet Archive's Wayback Machine, and get them back as a clean spreadsheet.

Built for accountability research: hand it a handle and a time range, get an
`.xlsx` with every recoverable tweet, its exact date, and a link to the
archived snapshot proving it.

## Quickstart

```bash
pip install -r requirements.txt
python recover.py --handle <handle> --from 2016-01-01 --to 2024-12-31
```

Output in `out/<handle>/`:

- **`<handle> - Recovered Tweets.xlsx`** — three sheets:
  - *Tweets*: Date · Tweet Text · Date Confidence · Source · Archive URL · Tweet ID · Capture Timestamp · Recovered Via · Is Retweet · Retweeted User
  - *Failed*: every unrecoverable ID with the honest reason
  - *Summary*: counts, recovery rate, date range, method & caveats
- **`tweets.csv` / `failed.csv`** — same data, flat, imports straight into Google Sheets

Interrupted? Re-run the same command — it resumes where it left off.

## How it works

1. **Discover** — asks the Wayback CDX index for every capture of
   `twitter.com|mobile.twitter.com|x.com/<handle>/status/*`, dedupes to unique
   tweet IDs. Also finds captures of the profile **feed page itself**
   (`/<handle>`, `/<handle>/with_replies`, paginated variants), dedupes them
   to one per day per variant, and evenly samples down to
   `--max-page-captures` (default 400).
2. **Extract pages** — fetches each feed capture and mines the ~20
   server-rendered tweets it shows, **including the account's retweets**
   (which individual tweet URLs can never surface). Runs first, so every
   tweet it recovers saves a per-tweet fetch.
3. **Extract** — fetches each remaining tweet's raw snapshot (`id_` URLs, no
   Wayback chrome) and pulls text from the legacy server-rendered markup or
   the `og:description` meta tag. Verbatim only; no text found = honest
   failure.
4. **Date** — decodes each tweet ID as a Twitter snowflake for an
   exact-to-the-second timestamp, validated against the capture time.
   Retweets are dated by the retweet's own ID (when the markup carries one) —
   i.e. when the account retweeted, not when the original was posted.
5. **Report** — builds the xlsx + CSVs. `--no-pages` skips the feed-page
   source entirely.

Typical recovery: ~85–90%. Two verified runs: 6,580 of 7,698 IDs (85.5%) and
3,272 of 3,658 (89.4%), both spot-checked verbatim against live snapshots.
Recovery tracks *era*, not capture density — post-2020 captures are often
client-side "JS shells" with no extractable text, which is the main
future-work target.

## Using with a coding agent

Clone the repo, open it in any coding agent (Claude Code, Codex, Cursor), and
say: *"Recover tweets for @handle between 2018 and 2022."* The agent
instructions in [AGENTS.md](AGENTS.md) cover the command, QA protocol, and
integrity rules. `CLAUDE.md` is a symlink to the same file, so Claude Code
picks it up automatically — edit `AGENTS.md` only.

## Future work

- Headless-browser pass over `Needs Browser = True` failures (JS shells)
- archive.today fallback for IDs Wayback lacks
- Direct Google Sheets export

## Comparative sources

See [docs/sources.md](docs/sources.md) — Wayback is primary; archive.today,
Politwoops, the Archive Team Twitter stream, and Memento fill gaps.
