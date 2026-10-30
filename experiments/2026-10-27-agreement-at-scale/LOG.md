# Agreement with the human stewards at scale (27 Oct 2026)

Three rounds ran on 27 Oct 2026: a 20-case pilot, the same 20 cases cropped to the replay, and a run on 58 cleaned cases.
On the 58 cleaned cases the pipeline agreed with the human verdict on 16 (27.6%), and the 60% mark fails.
Total spend was about $5.20 of Spark Open by the ledger ($1.16, $1.01 and $3.03 by round).
No mark changed after the first run.

## Question

How often does the pipeline's ruling match the human steward's decision on corpus cases, and which stage is to blame when it does not?
The pilot proves the plumbing and the stage attribution on 20 cases.
It does not test the 60% agreement mark, because 20 cases cannot.

## Method

Source: 597 spoken labels from 87 public steward-stream reviews, 584 of them with the video on disk.

### The labels are not the human decision (found before any model call)

All 597 labels are drafts: a pattern match on the steward's own captions, the last verdict phrase in a segment.
None has a human-reviewed label.
Segments are the presenter's talk, median 132 s, longest 2,628 s.
So the pilot scores against the steward's own words, read once by hand in a pilot, and only for cases that pass that read.

- Pool: window 20 to 120 s, label confidence at least 0.6, verdict penalty, no_action or racing_incident, video on disk: 191 labels (92, 61 and 38).
- First draw, 20 labels with a 300 s window cap: 7 of 20 closing quotes had no verdict at all (outros, announcements) and 3 windows held several incidents.
  No model had run, so the window cap went from 300 s to 120 s and the draw was redone.
- Second draw: seeded order by sha256 of seed and label id, at most 2 a video, a quota of 8 penalty, 6 no_action and 6 racing_incident, spares in order.
- Quote check: the last 300 characters of each window were read.
  A case stays only if the steward states a verdict on one incident there, and a dropped case is replaced by the next spare in its stratum.
- Result of the check: 35 labels read, 15 dropped, 20 kept from 17 videos, 1,097 s of window in all.
- The quotes are kept with this experiment's private record, because they name drivers.

### The pipeline

Per case, `meta-models/muse-spark-open-1026` on Baseten through the metering proxy, temperature 0, a 12,000-token ceiling:

1. LOCATE: frames every 1.5 s (1.7 s on the longest window) of the label window at 512 px, tiled 3 by 3 into labelled contact sheets, at most 8 sheets.
   No verdict is asked; it returns whether an incident is seen and its second.
2. RULE: frames from 4 s before to 8 s after the located second, every 0.75 s at 640 px, tiled the same way, with the generic sporting code, asking for a verdict.
   It is skipped when LOCATE finds no incident.

No caption, transcript, label or verdict word reaches a prompt.
Contact sheets are used because Baseten refuses more than 8 images a call (found in [the steward panel](../2026-10-27-steward-panel/LOG.md)).

### What is not in the pipeline, and why

The plan named the report normaliser, smoke A's closed set, smoke B's clock fix and smoke C's contact gate.
All four read PitBot replay telemetry, which exists only for the 12 PitBot answer-key cases in [Discovery 3](../2026-10-26-discovery-3/LOG.md), not for the 87 reviews.
So identity is scored only by what the model says it can name, and contact is the model's own read, not the mask gate.
I was told of this deviation before the run.

## Marks, fixed before the first run

| Id | Pilot mark |
|---|---|
| P1 | At least 18 of 20 cases end with a parsed LOCATE reply (finish `stop`) and, where LOCATE found an incident, a parsed RULE reply |
| P2 | Every miss gets exactly one stage from the rubric below, from a fresh grader; "cannot tell" on at most 20% of misses |
| P3 | At most $0.15 a case by the proxy ledger; hard cap $3.00, enforced in code |
| P4 | Every figure recomputes from the saved replies, byte-identical on two runs |
| P5 | All 20 cases carry a human-read quote before the run |

A miss is a case with no ruling, or a ruling whose verdict differs from the human verdict.
Agreement is an exact match on the three classes penalty, racing_incident and no_action.

| Id | Full-run mark |
|---|---|
| F1 | Verdict agreement at least 60% on scorable cases |
| F2 | "Unable to identify" under 25%: a penalty ruling whose offender is null or that says it cannot identify the cars, plus every case where LOCATE finds no incident |
| F3 | Every disagreement traceable to one named stage |

Stage rubric, first rule that applies wins:

1. label: the human verdict is not supported by the quote on a second read, or the window holds more than one incident.
2. locating: LOCATE found no incident, or its second is more than 10 s from the incident the steward discusses.
3. contact: the moment is right but RULE says contact where none is visible, or misses contact that is visible.
4. identity: moment and contact right, but the cars or roles are named wrongly, or the offender is null where the ruling turns on who.
5. ruling: the facts above are right and the verdict still differs.

The grader sees the quote, both replies and the sheets at the located second, and never sees the other cases' results.

## Round 1: the pilot

A fresh grader (Claude Opus) assigned the 15 misses their stage.
One grader, one pass, so its stage calls are a reading of the frames, not a measurement.

| Measure | Result |
|---|---|
| Verdict agreement | 5 of 20, 25% (95% Wilson interval 11% to 47%) |
| Cases with no ruling | 4 (LOCATE found no incident in 3 and hit the token limit in 1) |
| "Unable to identify" (F2) | 3 of 20, 15% |
| Both calls parsed, finish `stop` | 19 of 20 |
| Cost by usage and by the proxy ledger | $1.1632, $0.058 a case |

P1 to P5 all pass.

| Stage | Misses | What happened |
|---|---|---|
| locating | 4 | no incident found in 3, token limit in 1; one located a looping intro tile, not the reviewed footage |
| contact | 3 | right moment, wrong contact read (two said no contact where there was some, one inferred contact from smoke) |
| identity | 3 | right moment and contact seen, offender left null on a ruling that turns on who |
| ruling | 3 | facts right, verdict differs |
| label | 2 | the window holds no incident, or two incidents, after all |

- The replay tile was unreadable at 512 or 640 px in 9 of the 15 graded cases.
- One case shows the steward's penalty dialog on screen in every tile; it was ruled `no_action`, so the leak did not flatter the model, but the case is not clean.
- Looping intro tiles and logo interstitials caused two locating misses.
- All 5 hits are no_action or racing_incident, and 0 of the 8 human penalties was matched.
  The model ruled penalty on 2 of its 16 rulings, the cautious answer seen in the steward panel.

## Round 2: crop to the replay region, same 20 cases

Only the frames changed: every frame was cropped to the bottom half of the 1280 by 720 frame, which holds the replay tiles in every layout seen, and the tiles grew (LOCATE 640 px a tile, RULE 2 by 2 at 960 px).
The crop was set by eye from one frame per video.
The mark fixed before the run: the crop counts as the main lever only if agreement reaches 8 of 20.

| Measure | Round 1 | Round 2 |
|---|---|---|
| Verdict agreement | 5 of 20 (25%) | 5 of 20 (25%) |
| Cases with no ruling | 4 | 6, two of them LOCATE hitting the length limit |
| "Unable to identify" | 3 of 20 | 5 of 20 |
| Penalties matched, of 8 | 0 | 1 |
| Cost | $1.1632 | $1.0063, $0.050 a case |

- The crop mark fails: resolution is not the main lever.
  Agreement did not move, and only 2 of the 5 hits are the same cases as round 1.
- The grader still marked the replay unreadable in 9 of 15 cases.
  The overhead shots show cars a few pixels wide, so cropping cannot add detail that is not in the file.
- The round 2 grader called 6 misses `label` against 2 in round 1, so two graders disagree on the same footage and the stage split is soft.
- Stage table: label 6, locating 3, contact 3, ruling 2, identity 1.

## Round 3: a cleaned label set, then a run on it

### Cleaning

- Pool: the pilot's 191 labels.
- Two independent passes of fresh readers (Claude Opus) read each window's caption text and nothing else.
  For each window they returned whether it rules on exactly one incident, the verdict the steward states, and a short verbatim quote.
- A case enters the cleaned set only if both passes say one incident and give the same verdict in the three classes.
- Calibration mark, fixed before cleaning: against the 35 pilot reads, the pair must agree with them on 29 of 35 or better.
  If it fails, the cleaned set is not used before I decide.

| Measure | Result |
|---|---|
| Windows read in both passes | 191 of 191 |
| One incident, pass A and pass B | 75 and 78 |
| The cleaned set | 58 (penalty 26, no_action 18, racing_incident 14) |
| Cleaned verdict differs from the pattern-match label | 5 of 58 |
| Calibration against the 35 pilot reads | **24 of 35, the mark was 29: fails** |
| Of the 20 pilot keeps, the pair keeps with the pilot verdict | 9 (mark 17) |
| Of the 15 pilot drops, the pair drops | 15 (mark 12) |

- The pair is a high-precision, low-recall filter: nothing the pilot dropped got through, but it dropped 11 of the 20 pilot keeps.
- Four of the keeps it dropped were later called `label` misses by a grader (one in both rounds, three in round 2), so some of the pilot keeps were loose too.
- Only 58 of 191 windows (30%) hold one stated verdict by the two-reader rule.

### The run, on my override

I chose to run the 58 after the calibration failed.
That is my decision against the rule fixed before cleaning, and it is recorded as mine, not as the calibration passing.
The configuration is round 1's, unchanged; the 20 pilot cases also in the 58 reused their round 1 replies at no cost.
Two fresh graders staged a seeded sample of 40 of the 42 misses.

| Measure | Result |
|---|---|
| Verdict agreement | **16 of 58, 27.6%** (95% interval 17.8% to 40.2%) |
| Agreement where a ruling exists | 16 of 44, 36% |
| No ruling | 14: LOCATE hit the 12,000-token ceiling in 10, found no incident in 4 |
| "Unable to identify" (F2) | 5 of 58, 8.6% |
| Penalties matched | 5 of 26; the model ruled penalty 8 times in 44 rulings |
| Cost, usage-priced | $3.55, $0.061 a case (includes the reused round 1 replies for the overlap) |
| Cost, proxy ledger lines for Spark Open in the run window | $3.03 over 88 calls |

The ledger rose $5.47 over the run, but $2.44 of that is 80 Spark 1.3 calls from another run on the same proxy.

| Mark | Result |
|---|---|
| Agreement at least 60% | **fail**, 27.6% |
| "Unable to identify" under 25% | pass, 8.6% (it does not count the 10 length cases) |
| 40 sampled misses staged | pass, 40 of 40, 1 "cannot tell" |
| Parsed in both calls on at least 90% | **fail**, 48 of 58, 82.8% (all 10 failures are LOCATE `length`) |
| At most $0.15 a case, cap $20 | pass |
| Figures byte-identical on recompute | pass |

Human verdict, then model verdict:

| Human | penalty | racing_incident | no_action | no ruling |
|---|---|---|---|---|
| penalty (26) | 5 | 8 | 5 | 8 |
| no_action (18) | 1 | 6 | 7 | 4 |
| racing_incident (14) | 2 | 4 | 6 | 2 |

Stage table, 40 sampled misses: contact 13, locating 11, identity 7, ruling 6, label 2, cannot tell 1.

## What it shows

- On cleaned cases agreement is 28%, about the pilot's 25%, so label noise was not what held agreement down.
- The 60% mark fails by a wide margin: the top of the interval is 40%.
- Ten no-rulings come from LOCATE running out of its 12,000 tokens on a window of many sheets.
  That is a configuration limit, not a model failure, and a rerun with a higher ceiling or fewer images is the cheapest next step.
- Contact (13) and locating (11) lead the misses.
  A looping inset in the corner plays an intro video, and RULE read it as the incident in at least 6 cases; 19 of 40 graded cases have an unreadable replay.
- The model rarely rules penalty (8 of 44 rulings), so most human penalties become racing incident or no action.
- Two cases leak: a notice-to-driver dialog with a car number is on screen.
- The stages split widely in every round, so no single fix will lift agreement.

## What it does not prove

- The labels are the steward's words read through a pattern match and a quote check, not a reviewed answer key.
- The cleaned set failed its own calibration (24 of 35) and was run on my choice; the 58 are likely clean but not complete, and say nothing about the 133 windows left out.
- Graders ran one pass each, so stage splits are readings, not counts.
- Identity and contact are the model's read, not the telemetry closed set or the mask gate, so this is not the full pipeline of the design brief.

## Files

The draw, cleaning and scoring scripts, the case lists, the replies, the sheets, the quotes and the grades are kept with this experiment's private record.
The quotes and replies name drivers and never enter git.
