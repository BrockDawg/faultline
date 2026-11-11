# Round 4: the demo backbone (28 Oct 2026, overnight)

## Question

Can the demo stand on its own record?
Five tests, all pre-registered before the first paid call:

- Can the ledger be published under the model and video terms, and does it pass a leak lint, gitleaks and 50 MB?
- The clone test: can one command, with no API key and the network off, replay the whole synthetic shift into a rulings list to a byte-identical hash on two platforms?
- Four inputs and the real decision lifecycle on 12 incidents from a PitBot league.
- The abstention test: does Spark Open say "unable to rule" when the evidence cannot support a ruling?
- A three-minute dry run of the demo storyboard with readers who have never seen the project.

Spend cap $8.00 through the metering proxy, with per-test caps enforced in code before every paid call: clone test $2.50, four inputs $3.50, abstention $2.00, the rest $0.
Every call was priced from its own reply's usage and matched to its ledger line by model and token counts, so the reported spend is the ledger's.

## Can the ledger be published? ($0)

The redistribution, caching and attribution clauses of eight terms pages were read and quoted, with the URL and a hash of each page's text.

| Artefact | Verdict | Condition |
|---|---|---|
| SAM 3.1 masks and boxes (Meta Model API) | conditional yes | Outputs belong to the user; keep any Meta provenance mark; do not invite training of competing models on them; do not market benchmarks for a competing product |
| Spark Open replies verbatim (Baseten) | conditional yes | The Muse licence requires "Built with Muse Spark Open" shown prominently; do not present replies as human-written; whether Baseten is a Meta hosted platform is unconfirmed, and if it is, the SAM conditions apply too |
| Spark 1.3 replies (Meta Model API) | conditional yes | The SAM conditions |
| Kling 3.0 Turbo frames (Higgsfield) | conditional yes | Label the frames AI-generated (Kling 3.0 Turbo via Higgsfield), because a JPEG drops the C2PA data; Higgsfield bans training on its outputs; crediting Kling and keeping the frames non-commercial is the cautious reading |

Two cautions: Meta's acceptable use policy names uses related to the operation of heavy machinery, and whether an after-the-fact review of forklift footage falls under it is a question for the terms; and tracking an identifiable person across frames needs a lawful basis on a real site.

| Check on the clone-test export (111 replies, 148 frames, the trace) | Result |
|---|---|
| Clip names and folder paths in any string | 0 |
| League or driver names | 0 real; 12 lint hits, all false (a colour word in box descriptions, and strings inside encoded masks) |
| gitleaks | clean, after a ledger field named `key` was renamed |
| Size | 7.99 MB for the whole shift |

All four marks pass, and no artefact class has to become hashes before publication.
Publication needs the "Built with Muse Spark Open" line, an AI-generated label beside the frames, and no wording that invites training on the ledger.

## The clone test

The shift: 38 synthetic clips (the 28 of [smoke test D](../2026-10-27-smoke-d-forklift-locator/LOG.md) plus the 10 round-2 aisle clips), shuffled by a fixed seed, 640x360 at 24 fps, 571.6 s in all.
Perception by script (smoke test D's locator), then per window two SAM 3.1 calls ("forklift", "person") on the middle frame, a script fact sheet, and one Spark Open ruling over the four site rules plus a travel-speed rule.
The populating run sent every request through the proxy once and recorded each reply against the sha256 of its request body.
The replay client has no HTTP code path: it rebuilds every request from the recorded frames and trace, computes the key and reads the reply from the record; a missing key is a hard error.

| Mark | Result | Verdict |
|---|---|---|
| Same hash on two platforms | Windows (fresh copy, offline) and a Modal CPU container with the network blocked give the same `demo.sha256` | pass |
| Zero cache misses, zero bytes to a model host | 0 misses; the Windows replay turns every socket connect into an error, and neither platform raised | pass |
| Every row carries rule, offender, window, fact sheet, tier, cost, finish and input hash | 185 rows, all fields | pass |
| Replay under 6 minutes in the container | 12.6 s (16.3 s with start-up) | pass |
| No round-2 breach clip missed | 2 of 5 missed: 39 (separation, "no metric scale") and 36 (speed, ruled compliant); compliant 31 (a still spotter) ruled a spotter breach | **fail** |
| Ledger under 50 MB | 7.99 MB | pass |
| Two Windows replays identical | yes | pass |
| GitHub Actions | not run | not run |

- The full road rebuilt the trace and all 148 frames from the shift video on Windows: same trace, 0 differing frames, same hash, 40.9 s.
  It did not run in the container, so whether Linux ffmpeg extracts the same JPEG bytes is still open.
- The locator raised 37 windows, one on each non-idle clip, and none in the idle gaps.
- 185 rulings (37 windows x 5 rules): compliant 83, not applicable 58, cannot tell 24, breach 15, missing 5.
  The 5 missing rows are one window, the clearest collision in the set, where Spark Open ran to its 12,000-token ceiling and returned nothing.

What it does not prove: it proves the record replays to the same bytes, not that SAM or Spark Open would regenerate the same replies.
The rulings are on AI-made clips scored against folder labels.
A machine with no network and an empty package cache would need a prebuilt wheel for the first run.

## Four inputs and the real lifecycle on 12 PitBot incidents

Names were scrubbed to car numbers by a fixed per-case map before any prompt, a script failed any case where a name token survived, and a separate reader checked all 12 texts for leaks before the first paid call: 0 of 12 leaked by either check.
These incidents went to Meta models only.

Arms, Spark Open at temperature 0, the same generic sporting code and verdict schema:

| Arm | Right | Wilson 95% | Penalty rate |
|---|---|---|---|
| (a) the driver's report only | 1 of 12 | 2% to 35% | 0% |
| (b) the steward's narration, verdict words cut | 9 of 10 | 60% to 98% | 90% |
| (c) a telemetry sheet only | 2 of 11 | 5% to 48% | 0% |
| (d) frames alone (cached [Discovery 3](../2026-10-26-discovery-3/LOG.md) W1-03 replies) | 5 of 5 | 57% to 100% | 80% |

Arm (b) exists on 10 cases (two have no narration), and one arm (c) call ran to its ceiling and returned nothing.

The lifecycle on top of arm (c): stage 2 feeds the driver's report as a protest, stage 3 the steward's final reasoning.

| Mark | Result | Verdict |
|---|---|---|
| Arm (b) at least 9 of 12 | 9 of 10 available | pass |
| Arm (c) at least arm (d) on shared cases | 1 of 5 against 5 of 5 | **fail** |
| Moves toward the reporter on no_action cases at most 1 | 0 of 2 | pass |
| Concedes to the steward on at least half of stage-1 disagreements | 2 of 10 | **fail** |
| Wrong defences at most 2 | 7 | **fail** |
| Rescore to the same hash | yes | pass |
| Every call finishes `stop` | 69 of 70 | **fail** |

- The ruling step rules well on the stewards' own facts (9 of 10), so on these 12 the gap is in what the model is given.
- Telemetry alone is the weakest input (2 of 11, never a penalty): the sheet carries the second, not the blame.
- The driver's complaint does not sway Spark Open toward a penalty; it pulls the other way.
- Once it has ruled from telemetry, Spark Open holds its ruling against the steward's reasoned final in 7 cases, so the demo shows the lifecycle as a human-labelled log over one model ruling.

n = 12 (10 penalties), so no difference under about 30 points is real.

## The abstention test

Items, keyed before any call: 10 racing windows cut 1 s before the contact, 2 racing windows with a hard cut at the contact (fewer than the planned 5 existed), 5 forklift windows with no truck or with the rear path out of frame, and 10 sufficient controls.
Two prompts per item: forced (verdict classes only) and open (adds "unable to rule" with a required missing-fact list).

| Mark | Result | Verdict |
|---|---|---|
| Forced fabrication on the 17 insufficient items | 3 of 17 | reported |
| Open prompt refuses insufficient items (80%) | 11 of 17 (65%, Wilson 41% to 83%) | **fail** |
| Refuses at most 2 of 10 controls | 4 of 10 | **fail** |
| Agreement on ruled controls at least the earlier run's | 5 of 6 (earlier: all 10) | **fail** |
| Named missing fact matches the key (75%) | 11 of 11 | pass |
| Candidate seconds inside the window | all | pass |

Offered abstention, Spark Open refuses most windows that cannot show the touch and names the right missing thing every time it refuses.
It also refuses 4 of 10 windows a human ruled on, and still rules on 6 of 17 that cannot support a ruling.
So abstention offered to the model is a crutch: a script gate should decide sufficiency, and the model's "unable to rule" runs only on the gate's say-so.

## The three-minute dry run ($0)

A 12-shot storyboard rendered by script from the artefacts above, read by three readers who had never seen the project (Claude, not people).

| Mark | First round | Second round, fixed storyboard |
|---|---|---|
| SAM 3.1 as perception and Spark Open as ruler in the right beats | 3 of 3 | 3 of 3 |
| Every reader calls it a judge | 3 of 3 say "judge" | 3 of 3 say "judge" |
| Rerun command named | 3 of 3 (`uv run demo`) | 3 of 3, each noting it replays rather than reruns the models |
| "Unable to rule" read as a feature | 3 of 3, with a caveat | **0 of 3**: "6 ruled anyway" turns it into a failure |

The first round's cut list: a "single camera feed" over a grid of cameras, "hours of footage" over a 571 s shift, and "12 real decisions" over counts of 10, 5, 11 and 12.
Those were fixed and the stills rendered again; nobody flagged them in the second round.
The second round's points are pitch decisions, not render fixes: the four-input shot argues against the product, the warehouse rulings carry no accuracy figure although the clips have labels, and the replay shots prove the replay, not the judge.
The second round asked the readers to be blunt, so the two rounds are not like for like, and no human reader took part.

## Cost

| Test | Calls | Ledger | Cap |
|---|---|---|---|
| Clone test, populating run | 37 Spark Open + 74 SAM | $1.0294 | $2.50 |
| Four inputs and lifecycle | 58 Spark Open + 12 Spark 1.3 | $1.0810 | $3.50 |
| Abstention | 54 Spark Open | $1.0242 | $2.00 |
| Terms, replays, dry run | 0 paid | $0 | $0 |
| Total | 235 | **$3.1346** (plus one $0.0025 SAM probe) | $8.00 |

The replays and the container leg made no model calls; the container used a few seconds of Modal CPU.
Frames, replies and storyboard stills stay private, because the stills hold generated frames.
