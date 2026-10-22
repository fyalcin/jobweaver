# This repository is a trimmed copy of a private deployment

Jobweaver started as a private tool for one household. That repository's history holds password hashes, a
production database, real CVs and scraped recruiter contacts, so it never goes public. This repository is the
private app trimmed to what anyone may legally and safely run, copied into a new repository whose history starts
with one commit (October 2026). Improvements are made here, in public.

## Considered options

- Rewrite the private history (`git filter-repo`) and publish that repository: one missed file publishes personal
  data, and the history is mostly database snapshots anyway.
- Rebuild from scratch: cleaner, but weeks slower, while the trimmed app already works.

## Consequences

- The author's own deployment moves to this code; personal parts (private notification and model routes,
  personal configuration) live in a separate private add-on that plugs in through the public contracts.
- Trimming removed what a public user may not run: readers that fetch sites directly against their terms or evade
  bot protection (python-jobspy, selenium-stealth, a spoofed browser User-Agent), a model route through a
  subscription login whose terms forbid third-party use, an unauthenticated database browser, and all personal
  data.
