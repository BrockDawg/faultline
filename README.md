# faultline

faultline is a rules-compliance judge for video.
Give it a rules pack and footage, and it says for each rule whether it was followed and who broke it.
Every output is a ruling: the rule, the offender and the evidence, never tips or statistics.
It covers two domains today: warehouse forklifts, under OSHA 29 CFR 1910.178 and each site's own rules, and sim-racing leagues on PitBot (pitbot.gg), Brock's league management platform.

## How it works

### Rules packs

A rules pack is a folder of markdown rule files plus one `pack.json`.
`pack.json` holds a `name`, a `version` and a `domain`, all non-empty strings, an optional `source`, and an optional `unique_ids_across_domain` flag.
Each rule file opens with a header between two `---` lines that gives the rule's `id` and `title`, then the rule text.
A forklift rule also says what a breach looks like on footage (`On video:`) and names its clause (`Source:`):

```
---
id: travel_speed
title: Travel at a speed that allows a safe stop
---
Drive at a speed that lets the truck stop safely. Keep to the site's authorised speed limits and traffic rules.

On video: The truck cannot stop before a person, truck or object that was in view in time. The truck brakes hard, slides, or goes faster than a speed limit shown in the clip.

Source: 1910.178(n)(8), 1910.178(n)(1)
```

### The loader

[`src/faultline/pack.py`](src/faultline/pack.py) loads packs with the standard library only.
`load_pack(folder)` loads one pack, and `load_packs(root, domain=None)` loads every pack folder under a root, or one domain's.
Rule files are read in file-name order, as UTF-8 with any line endings, and each rule keeps its `Source:` clause as `source_clause`.
A broken pack stops with a `PackError` that names the file and the reason, such as a missing field, an unclosed header or a rule id used twice.
Packs flagged `unique_ids_across_domain` may not share a rule id with another flagged pack in the same domain.

### The packs shipped

| Pack | Domain | Rules | Source |
|---|---|---|---|
| `forklift-operating-travel` | `warehouse-forklift` | 14 | OSHA 29 CFR 1910.178 |
| `forklift-loads-stacking` | `warehouse-forklift` | 7 | OSHA 29 CFR 1910.178 |
| `forklift-pedestrians-site` | `warehouse-forklift` | 10 | OSHA 29 CFR 1910.178 |
| `forklift-truck-checks-fuelling` | `warehouse-forklift` | 15 | OSHA 29 CFR 1910.178 |
| `forklift-site-rules` | `warehouse-forklift` | 4 | Site rules |
| `oval` | `sim-racing` | 20 | PitBot Rule Library |
| `road-gt` | `sim-racing` | 21 | PitBot Rule Library |
| `open-wheel` | `sim-racing` | 19 | PitBot Rule Library |

The site pack holds rules a site sets for itself, and each of its rules says so in its `Source:` line.
The sim-racing packs and the site pack carry `[placeholders]` where each league or site sets its own values.
Every forklift rule has an `On video:` line, every OSHA rule cites a 1910.178 clause, and the tests check both.

### Built, and still in design

Built: the pack format, the loader, the eight packs, their tests and the provenance tooling.
In design: the steward model pipeline that reads footage and writes the rulings.
It is being designed from the measurements below, and no code in this repo calls a model yet.

## What was measured before designing

Before designing the steward, we measured what Meta's models can and cannot do on real league footage, with real driver reports and human steward decisions as the answer key.
Each experiment has one log with the question, the run, the cost, the findings and the decision; the index is [experiments/README.md](experiments/README.md).

**[Capability probe](experiments/2026-10-26-capability-probe/LOG.md), 26 Oct.**
What can Meta's models do on each candidate steward feature?
All 29 probes that can run have run: 15 worked, 14 worked badly.
The top score, 0.75, went to a local uncertainty signal for the router.

**[Steward limits](experiments/2026-10-26-steward-limits/LOG.md), 26 Oct.**
Given a driver's incident report and the evidence clip, can a video-only steward work out who is who, find the incident, rule correctly and show evidence a human steward can check?
The first batch scored 18 right, 4 wrong and 3 not scorable for $1.998; the second scored 18 right, 5 wrong and 10 not scorable for $5.14.

**[Router tier 2: Spark Open](experiments/2026-10-26-router-spark-open/LOG.md), 26 Oct.**
Can Muse Spark Open replace `muse-spark-1.3` as the router's tier 2 without losing answer quality?
Spark Open passed 49 of 55 (89.1%) against Spark 1.3's 50 of 55 (90.9%), at about the same cost per call.
Brock switched tier 2 to Spark Open, because it scored close and the steward should use more of Meta's open-weights models.

**[Discovery 3](experiments/2026-10-26-discovery-3/LOG.md), 26 Oct.**
Which of 28 follow-up tests on footage, telemetry and tools change the steward design?
26 of 28 tests ran for $5.59, and the pipeline finds the moment but fails on who is who.

**[Router tier 1: Glimmer on Modal](experiments/2026-10-27-router-glimmer-modal/LOG.md), 26 and 27 Oct.**
Can Muse Glimmer on a Modal L40S answer tier 1 at a usable speed, and which of the 220 labelled prompts can it answer?
Glimmer answered all 220 prompts from Modal in 14 minutes, where the local GPU takes about 50 s a call.
The routed bench scored 92.7% (51 of 55), level with sending everything to tier 3, at a list price of $0.82 against $2.37.

### What the measurements settled

- **The moment is found; identity is the hard part.**
  Timing landed within 1 s on most clips, and the misses were identity: misread digits, on-screen labels trusted over the car, or a touch the camera never showed.
- **The report picks the incident.**
  Without one, a 50 s clip with five spins has no single answer, and on 18 human-steward windows with no report Spark scored 5 of 18.
- **Identity comes from the screen.**
  The replay overlay names the camera's driver and car numbers are readable, while PitBot's roster is wrong for past races, so it is a flagged fallback.
  Forklifts follow the same design: a visible fleet number plus the site's own roster, never faces.
- **Telemetry gives the second, not the blame.**
  The models read incident counters literally, so the blame rule goes in the prompt, including "a car forced off registers no incident points".
- **The agent shape works.**
  Spark with tools got the verdict right 6 of 6 (roles 4 of 6) and asked for telemetry first every time.
  Spark Open drove the same tools on Baseten and wrote the best evidence plans, 12 of 12, at about $0.005 a plan.
  Meta's API has no way to switch tools off, so the steward must send "tools are closed" to get a ruling.
- **Spark rules; SAM supplies frame-level evidence.**
  SAM alone misleads, because occlusion reads as touching, and broadcasts need a shot-cut gate before any SAM measure.
- **Output headroom is a correctness setting.**
  At 8,000 output tokens a third of strict-schema calls reasoned to the ceiling and returned nothing; 16,000 fixed every one.
- **Minimal reasoning effort is the triage setting**: same or better rulings, 0.27 of the output, valid JSON every time.
- **Stated confidence carries no signal yet.**
  Spark got 5 of 10 rulings right and said 0.9 on a wrong call.
- **Glimmer reads the broadcast clock strip digit-exact** (7 of 7 finished reads), but locally it spends its whole token allowance thinking and runs 36 to 600 s a read on a shared 12 GB GPU.
- **A filename can leak the answer.**
  Spark Open scored 19 of 20 on forklift clips with the filename, which names the label, in the prompt, and 11 of 20 with an opaque case reference.
- **The router's judge checks topic, not correctness.**
  The local 7B judge passed Glimmer on 206 of 220 prompts, so label moves rest on a stricter re-judge (129 of 206 passed) and a second read of each move.
  The router with a tier-3 floor scores 76.4% with 0.0% under-route on the 55 held-out prompts, and only 5 of 55 reached tier 1: it saves money mostly through tier 2.

## Meta models used so far

| Model | Id | Served by | Measured for |
|---|---|---|---|
| Muse Spark 1.3 | `muse-spark-1.3` | Meta Model API | rulings from frames, reports and telemetry; router tier 2 until 26 Oct |
| Muse Spark Open | `meta-models/muse-spark-open-1026` | Baseten | router tier 2; evidence planning and tool use; native video |
| Muse Wonder 1.0 | `muse-wonder-1.0` | Meta Model API | router tier 3; deeper rulings |
| Muse Glimmer | `muse-glimmer:30b` | Ollama, locally and on a Modal L40S | router tier 1, from Modal with the local copy as fallback; reading the clock strip |
| SAM 3.1 | `sam-3.1` | Meta Model API | masks, tracking and contact frames |
| Muse Voice Transcribe 1.0 | `muse-voice-transcribe-1.0` | Meta Model API | transcribing race audio |
| Llama 3.2 1B | `llama3.2:1b` | locally | router tier 1, replaced by Glimmer on 26 Oct |

The task router sends each call to one of three tiers: Glimmer, then Spark Open, then Wonder.
A classifier trained on the labelled prompts picks the tier, and Glimmer's labels were remeasured by asking it every prompt and judging the answer.
The judge is Qwen 2.5 7B (`qwen2.5:7b`), run locally; it is not a Meta model and never answers a prompt.

Every paid call went through a metering proxy that holds the API key and enforces a spend cap, apart from two direct calls to Baseten of well under a cent.
The probe ledger, shared by the capability probe, the steward limits and Discovery 3, stood at $13.82 of its $20 cap after Discovery 3.
The router ledger stood at $3.3158 after the Glimmer bench, under a $10 cap in code, the only cap on Baseten spend.
Glimmer on Modal used $2.68 of GPU time, all covered by Modal's $30 starter credits.

## The tooling behind the work

These tools are private and not in this repo; [PROVENANCE.md](PROVENANCE.md) says what each one is and what changed during the hackathon.

- **Metering proxy**: holds the API key and enforces spend caps.
- **Task router**: routes each call to a tier of Meta models.
- **Capability probe**: probes vision models, including a contact detector built on SAM.
- **Tournament harness**: runs many coding agents on one brief and grades them against held-out human steward decisions.
- **Corpus scraper**: gathers steward footage and comments.

## How to run

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
```

Load the packs from Python:

```python
from faultline.pack import load_packs

for pack in load_packs("packs", domain="warehouse-forklift"):
    print(pack.name, len(pack.rules))
```

After cloning, run `uv run python scripts/install_hooks.py` once.
It copies `.githooks/commit-msg` into the clone's hooks folder and sets default trailer values, and it refuses if git's `core.hooksPath` is set.
The hook fills a missing `Built-With` or `Meta-Models` trailer from those defaults, stamps a missing `Built-On` with the local time, and refuses a commit with a blank trailer or no value to fill one.
Hand-written commits say so in the message with `Built-With: <name> (by hand)`.
`uv run python scripts/check_provenance.py` checks the trailers over the whole history, and `uv run python scripts/build_log.py --write` regenerates the build log.

## Repo map

- `src/faultline/pack.py`: the rules-pack loader.
- `packs/`: the eight rules packs, and the format in `packs/README.md`.
- `experiments/`: one log per measured experiment, with an index.
- `tests/`: tests for the loader, the shipped packs, the hook, the history check, the build log and the provenance text; `tests/fixtures/` holds two small packs.
- `scripts/`: the hook installer, the history check and the build-log generator.
- `.githooks/commit-msg`: the provenance hook.
- `PROVENANCE.md`: what was built during the hackathon, what existed before it, and the models used.
- `PROVENANCE_START`: the first hooked commit, where the history check starts.
- `BUILD_LOG.md`: the dated log of every commit.
- `pyproject.toml`, `uv.lock`: the project and its locked dev tools.

## Provenance

[PROVENANCE.md](PROVENANCE.md) says what was built during the hackathon, what existed before it, and which models were used.
[BUILD_LOG.md](BUILD_LOG.md) is the dated log of every commit, generated from git.
Every commit after the first two carries three trailers: `Built-With`, `Meta-Models` and `Built-On`.
