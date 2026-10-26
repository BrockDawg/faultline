# Provenance

This file says what in this repo was built during the hackathon, what existed before it, and which models were used.

## How to read this repo

The hackathon window opened at kickoff on 26 Oct 2026, 12:00 ET (11:00 Chicago).
It closes at the deadline on 4 Nov 2026, 9:00 PM ET (8:00 PM Chicago).
Every commit after the first two carries three trailers: `Built-With`, `Meta-Models` and `Built-On`.
The trailers are enforced on each commit by `.githooks/commit-msg` and checked over the whole history by `scripts/check_provenance.py`.
The first two commits, `3c19d45` (the workspace scaffold) and `11ea3dc` (the publish boundary), predate the hook and carry no trailers, but both are dated after kickoff.
The trailers record the models the build session declared.
`BUILD_LOG.md` is the dated log of every commit, generated from git.

## What existed before the hackathon

- The task router.
  Pre-existing tooling I'd built, which already routed to Meta models. During the hackathon we extended it to:
  - turn off Muse Glimmer's thinking mode on local calls, so it returns an answer instead of spending its whole budget thinking;
  - update its training labels.
- PitBot (pitbot.gg), Brock's sim-racing league management platform, with its paying leagues.
- Race telemetry and results data from PitBot leagues.
- Steward-report video footage and the human steward decisions from PitBot leagues.
- PitBot's Rule Library, the source of the `oval`, `road-gt` and `open-wheel` packs.
- The four `forklift-*` packs, based on OSHA 29 CFR 1910.178.
- The rules-pack format (a folder of markdown rule files plus `pack.json`) and an earlier private loader for it.
- Brock's development workflows (Claude Code with his own skills and orchestration).
- Private tooling Brock built, not in this repo:
  - a tournament harness that runs many coding agents on one brief and grades them against held-out human steward decisions;
  - an evaluation and scoring kit;
  - a capability probe for vision models, including a contact detector built on SAM;
  - a metering proxy that holds the API key and enforces spend caps;
  - a corpus scraper for steward footage and comments.

## Built during the hackathon

- This repo.
- The provenance hook (`.githooks/commit-msg`), its installer, and the history check (`scripts/check_provenance.py`).
- The loader in this repo (`src/faultline/pack.py`), rewritten from a written contract during the hackathon.
- Pack metadata edited to drop dates and internal file names; no rule text changed.

## Models used

- Building: `claude-opus-5-5` via Claude Code, on Brock's subscription.
- At runtime: Meta models, listed here as each is first used (none yet).
