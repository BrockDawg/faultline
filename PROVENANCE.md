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
  - serve Muse Glimmer from a Modal L40S as tier 1, through the metering proxy, with local Ollama as the fallback;
  - remeasure its 220 routing labels against Glimmer with a local judge.
- PitBot (pitbot.gg), Brock's sim-racing league management platform, with its paying leagues.
- Race telemetry and results data from PitBot leagues.
- Steward-report video footage and the human steward decisions from PitBot leagues.
- PitBot's Rule Library, the source of the `oval`, `road-gt` and `open-wheel` packs.
- The four OSHA `forklift-*` packs, based on OSHA 29 CFR 1910.178.
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
- The `forklift-site-rules` pack, four rules a site sets for itself: high-visibility clothing in a truck zone, a spotter when reversing, a set distance from people on foot, and no contact with racking or stock.
- Eleven measured experiments, logged under `experiments/`, 26 and 27 Oct: eight on the Meta models and three smoke tests run on scripts alone.
- The forklift scan route design note (`docs/forklift-scan-route.md`), 27 Oct.
- The two scenes in `assets/scenes/`, 27 Oct.
  Each piece in them (forklift, worker, rack bay, pallet, race car, track corner) was generated on Higgsfield with Nano Banana 2, then vectorized with Ideogram Vector.
  The pieces were cleaned and composed into the scenes by private scripts written the same day.
- The licence files `LICENSE` and `NOTICE`, and `assets/NOTICE.md`, 27 Oct.

## Models used

- Building: `claude-opus-5-5` and `claude-fable-5-1` via Claude Code, on Brock's subscription.
- Images: Nano Banana 2 (`nano_banana_flash`) and Ideogram Vector (`ideogram_vector`), both on Higgsfield.
- Measured in the experiments (`experiments/`), before any design: Muse Spark 1.3 (`muse-spark-1.3`), Muse Spark Open (`meta-models/muse-spark-open-1026`, served by Baseten), Muse Wonder 1.0 (`muse-wonder-1.0`), Muse Glimmer (`muse-glimmer:30b`, open weights on Ollama, on this machine and on a Modal L40S), SAM 3.1 (`sam-3.1`) and Muse Voice Transcribe 1.0 (`muse-voice-transcribe-1.0`).
  Llama 3.2 1B (`llama3.2:1b`) was measured as a router tier and dropped.
  The local judge in those experiments is Qwen 2.5 7B (`qwen2.5:7b`), which is not a Meta model and never answers a prompt.
- At runtime in this repo: Meta models, listed here as each is first used (none yet).
