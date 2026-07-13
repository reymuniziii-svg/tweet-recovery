# Comparative sources for archived tweets

The pipeline automates the Wayback Machine only. When coverage is thin — or
a specific missing tweet matters — these are the gap-fillers, in rough order
of usefulness.

| Source | What it adds | Caveats |
|---|---|---|
| **Wayback Machine CDX** (primary, automated) | Largest web archive; real bulk API; raw `id_` snapshots | Post-~2020 captures are often JS shells with no server-rendered text |
| **archive.today** (archive.ph/.is) | Captures Wayback misses; snapshots are *rendered*, so JS-era tweets often have visible text | No official API; CAPTCHA-hostile; per-URL manual lookups only |
| **Politwoops** (ProPublica) | Purpose-built archive of tweets *deleted* by US politicians | Only officials they tracked, only while tracked; project status varies — check availability |
| **Archive Team Twitter Stream** (archive.org collections) | Bulk-downloadable JSON of the public sample stream, ~2011–2023 | ~1% random sample — good for corroboration, hopeless for completeness |
| **Memento Time Travel** (timetravel.mementoweb.org) | One query federates Wayback, archive.today, national archives, and more | Discovery layer only; you still extract from whichever archive it finds |
| **polititweet.org / per-figure trackers** | Full-fidelity tracking of selected public figures, deletions flagged | Narrow subject lists; check whether your target was tracked |
| **X (Twitter) API** | Canonical data for tweets that still exist | Expensive; useless for deleted tweets — deletion propagates |

## Practical playbook

- **Bulk recovery** → this repo (Wayback CDX).
- **A handful of high-value misses** → try the same status URL on
  archive.today, then Memento.
- **Deleted tweets of a US politician** → check Politwoops first; it may have
  text Wayback never captured.
- **Corroborating a contested quote** → an independent second archive
  (archive.today snapshot or Archive Team stream JSON) is much stronger
  evidence than a second Wayback capture.

## Evidence hygiene

Always record the archive URL alongside recovered text — the snapshot *is*
the citation. For anything that might be publicly contested, save a fresh
archive.today snapshot of the Wayback capture itself (archive-of-archive)
in case availability changes.
