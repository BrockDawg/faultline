# Round 4: the racing ceiling (28 Oct 2026, overnight)

## Question

The [agreement-at-scale test](../2026-10-27-agreement-at-scale/LOG.md) had Spark Open agree with the human steward on 16 of 58 cleaned cases (27.6%).
That number has no denominator.
This experiment asks which half fails: the camera (the frame input), the model, or the key.

Five tests ran, in this order: the scoreboard, a ranking of the cached rulings, one SAM pass over the 58, an oracle ceiling from the steward's own words, and a frontier reader on the same frames.
A blind human panel on the same cases needs league stewards and did not run.
Everything above each result was written and committed before that test's first run, paid or not.

## How it ran

- The key: the 58 cleaned cases from public steward review videos (penalty 26, no_action 18, racing_incident 14, 36 videos).
- A frozen split by a hash of each label id: calibration 26 (penalty 15, no_action 6, racing_incident 5), held-out 32 (penalty 11, no_action 12, racing_incident 9).
- Spend cap $6.00 for the experiment, held in code: every paid call's usage-priced cost was logged before the next call, and a call was refused once the experiment total plus that test's own cap would be passed.
  Other experiments spent through the same proxy the same night, so the reported spend is the sum of this experiment's own calls matched line by line to the ledger, never a ledger delta.
- Frames, caption text, replies and masks stayed private; the log holds counts and tables only.

### The racing gate, fixed before the first call

The stopping rule for all racing spend, hashed and committed before any other test ran.
The first branch that holds is taken.

1. The Meta-side gap is real: the best frontier reader reaches 60% or more on frames.
2. Perception is the wall: the oracle reaches 70% or more and the best frontier reader is at or under 45%.
3. Racing is shown only as an "unable to rule" case if any of these holds: the oracle is under 50%, or the best frontier reader is at or under 45%, or the human panel's Fleiss kappa is under 0.2.
   Racing is then shown only as an "unable to rule" case, with the real decision lifecycle, and every racing item over $5 is frozen, except the SAM contact instrument, which also serves the forklift contact rule.
4. Mixed: every racing item over $5 waits for the human panel.

Racing spend to 4 November stays under $40 unless branch 1 fires.

### Detectable differences at n = 58

At 80% power, two-sided 5%: about 17 to 18 points for one arm against a fixed mark, 23 to 26 points between two independent arms, and about 12 points between two arms on the same cases (McNemar).
Every mark under the relevant figure is read as a direction.

## Results

### The scoreboard ($0)

The 27.6% in the new form; the scoreboard recomputes byte-identical on two runs.

| Measure | All 58 | Calibration 26 | Held-out 32 |
|---|---|---|---|
| Agreement | 16, 27.6% (17.8% to 40.2%) | 26.9% | 28.1% |
| Cohen's kappa (bootstrap 95%) | 0.056 (-0.073 to 0.191) | | |
| Constant answer (penalty) | 44.8% | | |
| Prior sampling | 35.6% | | |
| Penalty recall | 5 of 26 | | |
| Asymmetric cost (a wrong pass counts 2) | 63 | | |

The 27.6% is below the constant answer and below prior sampling, and its kappa interval holds zero.
On this key the ruling on frames cannot be told apart from chance.
The key holds only the 58, so the held-out claim is the 32-case half only.

### Ranking the 44 cached rulings by verdict and confidence ($0)

Score per case: 2 for penalty, 1 for racing_incident, 0 for no_action, plus the stated confidence.

| Measure | Result | Mark |
|---|---|---|
| AUC, 44 ruled (bootstrap 95%) | 0.623 (0.44 to 0.79) | at least 0.65: **fail** |
| AUC, all 58, no ruling lowest | 0.509 (0.35 to 0.67) | reported |
| Agreement with cuts set to the stewards' base rate, 44 ruled | 16 of 44, 36.4% (23.8% to 51.1%) | at least 45%: **fail** |
| Penalty recall with the cuts | 8 of 26 | at least 12: **fail** |

The score carries at most a weak order.
Moving the threshold to the stewards' base rate trades no_action calls for penalty calls without adding agreement, so penalty aversion is not a threshold on an informative score.

### One SAM pass over the 58

Per case, three SAM 3.1 image calls ("race car") at the located second and one second either side, and one SAM video call over 3 s prompted with the two largest boxes.
Deterministic reads from the replies: readability (median box height of the two largest cars, readable at 24 px or more), a shot-cut gate, mask adjacency, a momentum-exchange contact test, and a looping-tile flag.

174 image calls and 58 video calls, all returned.
Cost: $1.479, matched to 232 of 232 ledger lines, under a $2.00 test cap.

| Measure | Result | Mark |
|---|---|---|
| Readable | 57 of 58, median 67.5 px | at least 50%: pass |
| Earlier agreement, readable / unreadable | 16 of 57 (18% to 41%) / 0 of 1 | at least 40% and at most 20%: **fail** |
| Gate unreadable on the 19 cases graders tagged unreadable | 0 of 19 | at least 14: **fail** |
| Contact codes | apart 19, adjacent with no exchange 5, exchange 0, one track lost 32, cut 2 | |
| Measurable | 24 of 58 | at least 30: **fail** |
| "Apart" where the earlier run agreed and saw contact | 5 of 9 | zero: **fail** |
| Looping-tile flag | 43 of 58 | reported |

Why it fails: the whole-frame "race car" prompt finds the biggest cars in the onboard view (the camera car's own bonnet and the car ahead), not the small cars in the replay view.
So the readability score, the box prompts and every contact code measured the onboard view, not the incident.
The looping flag is confounded too: the steward replays the same incident several times, so frames repeat anyway.

Read after the fact, not a mark: boxes in the right half of the frame (the replay side) give a median of 49 px, 55 of 58 readable, and the gate marks 1 of the 19 tagged cases unreadable.
Car size does not track the graders' "unreadable", which was about numbers and liveries they could not read, not cars too small to see.

What it shows: a car-size gate does not separate the cases the model misses from the cases it gets.
The cars are big enough to see but not to identify, so readability needs an identity read (a legible number or livery), not a box height.
SAM as a contact instrument on these review streams needs the replay view located first.

The second read for the byte-identity check died with a memory error and was not rerun, so every SAM figure above comes from one read and that mark is unmarked.

### Oracle ceiling: rule from the steward's own description, verdict sentences cut ($0)

The plan: give Spark Open the caption text of each case with every ruling phrase removed, and see whether it rules right from human facts.
The leak mark, fixed before any paid call: a reviewer who sees no verdicts may find at most 3 of 58 texts that state or imply the decision, else no paid call.
One redaction revision was allowed, checked by a new reviewer.

| Step | Result |
|---|---|
| Redaction 1 (drop the last 15% of the window, verdict words and the lines either side) | median 57 words kept, 0 empty |
| Reviewer 1 | 36 of 58 leak |
| Redaction 2 (joined text, the league's own ruling words, 12 words cut either side of each match) | median 35 words kept, 4 empty |
| Reviewer 2 (new, never saw redaction 1) | 34 of 58 leak |
| Leak mark | **fail**, final |

By the rule frozen before any paid call, no model was sent the texts.
The leaks after redaction 2 are mostly fault assignment in the steward's own reasoning, not ruling words.
These stewards narrate fault and verdict in one breath, so the oracle cannot be run on raw caption words; it needs a structured extraction of facts first.

### Frontier reader on the masked frames ($0)

The earlier run's own frame times (17 frames per case), with the race-control log and penalty text masked, as 116 contact sheets.
Claude Opus read them on Brock's subscription, sheets and the same prompt only, no captions or labels, and returned 58 of 58 parsed answers.
The free-tier routes send text only, so no free-tier model could read a frame.

| Measure | Claude Opus, masked frames | Spark Open, earlier run (unmasked) |
|---|---|---|
| Agreement, all 58 | 23, 39.7% (28.1% to 52.5%) | 16, 27.6% (17.8% to 40.2%) |
| Kappa (bootstrap 95%) | 0.119 (-0.045 to 0.294) | 0.056 (-0.073 to 0.191) |
| Calibration / held-out | 30.8% / 46.9% | 26.9% / 28.1% |
| Penalty recall | 5 of 26 | 5 of 26 |
| Model penalty rate | 20.7% | 13.8% (8 of 58) |
| Asymmetric cost | 56 | 63 |
| Says it cannot identify the cars | 46 of 58 | |

Paired: Opus right where Spark Open was wrong on 14 cases, the reverse on 7, McNemar p = 0.19.
Model-to-model kappa on the 44 both ruled: 0.193.

The strongest reader that could run also sits under the constant answer, and its kappa interval holds zero.
It shares Spark Open's main fault: 21 of 26 human penalties become racing_incident or no_action.
Most of the 7-case gap (12.1 points) comes from the 14 cases where Spark Open was never handed a window.
It is one draw from one model, and the two arms differ in input (masked against unmasked) as well as model.

## The gate, read

The oracle figure is missing (the leak mark failed), the human panel's kappa is missing, and the best frontier reader is 39.7%.
Branch 3 holds on the frontier condition alone: racing is shown only as an "unable to rule" case.
Every racing item over $5 is frozen; the SAM contact instrument stays open for the forklift side.
The branch rests on one number from one model, read as a direction, and should be reread if a human panel lands well above chance.

## Which half fails

| Half | Evidence | Reading |
|---|---|---|
| Model | Spark Open 27.6%, Opus 39.7%, both kappa intervals hold zero, both turn 21 of 26 penalties into something else; ranking Spark Open's confidence gives AUC 0.62 | Not Meta-specific: two unrelated models fail the same way on the same frames |
| Camera | Opus cannot identify the cars in 46 of 58; graders called 19 of 40 replays unreadable | **The leading failure.** Cars are visible but not identifiable on 1280x720 review streams |
| Key | Stewards narrate fault and verdict together (34 to 36 of 58 leak); the constant answer beats every model; the human ceiling is unmeasured | Not ruled out |
| Ruling step on facts | blocked by the leak mark | Unmeasured |

The frame input fails for every model tried, and the model is not the half to fix.
The key cannot be cleared until people rate the same frames blind.

## Cost

| Test | Calls | Ledger |
|---|---|---|
| Scoreboard, ranking | 0 | $0 |
| SAM pass | 232 | $1.479 |
| Oracle | 0 (leak mark failed) | $0 |
| Frontier reader | Claude Opus on Brock's subscription | $0 |
| Total | | **$1.479 of the $6.00 cap** |

## Needs

- A blind human panel on the 58: the only number that can clear or convict the key.
- If an oracle figure is still wanted, a fixed fact sheet filled from the captions, then a ruling from the facts.
- If SAM readability is retried, locate the replay view per layout first, then ask for a legible number or livery.
