# Round 4: Meta-model use (28 Oct 2026, overnight)

## Question

Where can the Meta models do a job no script does?
Three tests, in this order:

1. Spark Open native video as the picker of the incident second, on racing and forklift footage.
2. The predicate census: can Spark Open compile each rule of the 110 in the packs into a closed predicate grammar, and decide which rules a camera can judge?
3. The hands-free exhibit: can SAM 3.1 find the truck, the people and the structures from text alone, with no hand-drawn box?

Spend cap $12 for all three, in code, with per-test ceilings of $5, $5 and $3 inside it.
The shared ledger carries no tag per experiment, so the cap counted this experiment's own calls priced from the usage each reply returned, and the reported spend is those calls matched to ledger rows by model and token counts.
No mark above a test's result changed after that test's first paid call.

## Test 1: Spark Open native video as the picker

### Deviations, raised before any call

- The 58 agreement cases have no true contact second (their key is a caption window and a verdict), so scoring against them would grade the model against itself.
  The racing windows are instead the telemetry-truthed events from the [Discovery 3](../2026-10-26-discovery-3/LOG.md) W0-02 catalogue: 21 events with video, plus no-incident controls.
- Report 15 windows are placed with the W0-01 offset (3808.5 ± 1.5 s), not the provisional one.
- Only 8 clean 64 s control stretches exist, so the controls are 18 at 16 s and 8 at 64 s, and the false-alarm mark scales to at most 1 of 18.
- 5 of the 21 events are one car leaving the track or spinning, so the prompt asks for every incident, not only contact.
- Telemetry says an incident happened in the session, not that the camera showed it: report 15 is one car's cockpit, report 46 a broadcast that shows one place at a time.
  So "inside the bound" is a lower bound on what the model could see.
- The forklift reference second is computed by a fixed per-rule script over test 3's SAM tracks, committed before any SAM reply existed.

### Method

- Per event, a 16 s and a 64 s window, the event placed at a seeded offset inside each.
  11 fine cases with a tight truth (5 s or less) score timing.
- 10 fps, 1280 px, masked for names; Spark Open with the video as a data URL, reasoning effort low, 12,000 tokens, temperature 0.
  The prompt asks for every incident with its clip second, kind and cars by livery, with no report, rule or verdict.
- Forklift: the 26 synthetic clips (5 s, 24 fps), the site rules as text, asking for the frame where the rule-relevant moment peaks and the truck and person boxes there; two runs per clip.

### Pass marks

| Id | Mark |
|---|---|
| a1 | At 16 s: timing within 2 s on at least 6 of the 11 fine cases |
| a2 | At 16 s: an incident inside the bound on at least 15 of 21 events |
| a3 | At 16 s: a false incident on at most 1 of 18 controls |
| b | 64 s reported beside 16 s as the ceiling test |
| c | A fit of prompt tokens on clip seconds names the frame sampler |
| d | Forklift: the model's frame within 1 s of the script's second on at least 18 of 26, both runs |
| e | Forklift: the two runs within 0.5 s of each other on at least 20 of 26 |
| f | Every call finishes `stop` |

If a1, a2 and d all pass, native video is the locator; if a1 and d both fail, the model is never the picker.

### Result, racing

70 calls (40 at 16 s, 30 at 64 s), all `stop`, no size refusal up to 28.8 MB.

| Measure | 16 s | 64 s |
|---|---|---|
| Fine cases within 2 s (of 11) | **6** (Wilson 28% to 79%) | 5 (21% to 72%) |
| Events with an incident inside the bound (of 21) | **4** (8% to 40%) | 6 (14% to 50%) |
| report 15 events inside (cockpit, of 12) | 1 | 1 |
| report 46 events inside (broadcast, of 9) | 3 | 5 |
| Controls with a false incident | **5 of 18** (13% to 51%) | 2 of 8 |
| Incidents reported per event window / per control | 0.64 / 0.56 | 2.05 / 0.38 |
| Prompt tokens per call | 2,724 every call | 7,588 every call |

| Mark | Result |
|---|---|
| a1 | **pass, 6 of 11**, exactly on the mark |
| a2 | **fail, 4 of 21** |
| a3 | **fail, 5 of 18** (4 of the 5 on report 46) |
| b | 16 s holds half the fine cases, 64 s does not, so the ceiling is between 16 and 64 s |
| c | **fixed rate, 1 frame a second**: prompt tokens = 1,115 + 101 a second (n = 70), so about 101 tokens a frame at 1280 px |
| f | pass, 70 of 70 |

- Spark Open sees one frame a second, so a contact shorter than a second can fall between two sampled frames.
- Its own `frames_seen` is not a count: it said 1 on 22 of the 40 short calls while the token bill shows 16 frames.
  The token count is the measure.
- When the camera shows the incident, native video places it, but it also reports incidents where telemetry says nothing happened, at about the same rate per window as on real events (0.56 against 0.64).
- By the rule written before the run: a2 and a3 fail, so native video is not the locator.
  It can place the moment once a script has opened a short window on footage that shows the incident.

### Result, forklift (scored with test 3)

52 calls, all `stop`, 1,458 prompt tokens every call (5 frames at 1 fps plus the text).
The script's second exists on 20 of 26 clips (none on the 4 structure clips, the idle clip and one clip where the truck never moves long enough).

| Mark | Result |
|---|---|
| d | **fail, 4 of 26 in both runs** (7 of 26 in each run alone) |
| e | **fail, 14 of 26** |
| f | **pass, 52 of 52** |

- The model does not see speed or reversing as a moment: on every speed clip and every lone reversing truck it gave no frame in at least one run.
- Its truck boxes are loose: 12 of 38 overlap SAM's at IoU 0.5 or more, median 0.41.
- So the model is never the picker on the forklift side, and the script owns the second.

## Test 2: the predicate census

### Method

- The 110 rules in the packs: 60 sim-racing (oval, road-gt, open-wheel) and 50 forklift (the five forklift packs).
- Committed before any call: the route definitions (scan, window or out), a schema of 31 fact fields, the grammar, a forklift route key transcribed from [the forklift scan route](../../docs/forklift-scan-route.md) (30 scan, 4 window, 16 out), and a racing route key written by a separate reader who saw only the route definitions and the packs (18 scan, 3 window, 39 out).
- The grammar is a JSON tree (compare, is, and, or, not, for at least n seconds, exists), three-valued; a literal must quote its span from the rule, and a bare number is a parse error.
  The parser is a whitelist walk with no eval.
- One Spark Open call per rule, temperature 0, 14,000 tokens.
- A bait arm: 19 rules against the schema plus five tempting fields (frame brightness, grey smoke, audio level, exhaust visible, operator head yaw).
- A withheld arm: 7 rules against the schema with truck speed and reversing removed.

### Pass marks and result

| Id | Mark | Result |
|---|---|---|
| 1 | 15 of 15 truck-check rules routed out, each naming a records source | **fail, 2 of 15**: 11 went to window, 2 to scan |
| 2 | 0 invented fields | **pass, 0** |
| 3 | 0 bare literals, every span in its rule | **pass, 0 and 0** |
| 4 | Route agreement: 45 of 50 forklift, 54 of 60 racing | **fail, 24 of 50 (48%) and 47 of 60 (78%)** |
| 5 | At least 100 of 110 parse, none on `length` | **fail on the second half:** 104 of 110 parse, but one racing rule ran out at 14,000 tokens |
| B | Bait: at least 17 of 19 out or window, 0 predicates on a bait field | **fail on the second half:** routing 18 of 19, but 3 predicates read a bait field (head yaw for watching the travel path, in both runs; grey smoke for exhaust sparks, once) |
| W1 | Withheld: 7 of 7 list speed or reversing as needed | **fail, 2 of 7** |
| W2 | Withheld: 0 of 7 rule breach without them | **fail, 5 answers on 3 rules** |
| S | Bait and withheld: the same route in two runs on at least 24 of 26 | **fail, 22 of 26** |

- The schema leaked motion through a side door: the separation rule replaced "moving" with a stationary-seconds field left in the schema.
  A withheld-fact test needs every proxy for the fact removed too.
- On the main census, a second run kept the same route on 43 of 60 rules and an identical predicate on 35 of 60.
- The grammar holds: 0 invented fields, 0 bare literals, every literal quoted from its rule.
  A closed grammar plus a whitelist parser keeps the compiler faithful to the vocabulary.
- Judgeability does not hold: the model sends truck checks to window, under-claims what a script can raise and over-claims what a camera can show, and about a quarter of routes change between runs.
- By the rule written before the run, the design keeps a hand route key per pack, with the model drafting predicates a person approves.
- Racing agreement is higher mostly because 39 of 60 racing rules are plainly out (conduct, membership, appeals); on the 21 the key calls scan or window, the model agreed on 8.

The keys are readings, not a truth: the forklift key is the design note's own table, the racing key one reader's.

## Test 3: the hands-free exhibit

### Method

The 26 clips at 12 fps, 1280 x 720, one SAM 3.1 video call per clip per concept, text prompt only: "forklift", "person", "pallet racking upright", "wooden pallet".
Scored against the hand truck boxes of [smoke test I](../2026-10-27-smoke-i-floor-plane-speed/LOG.md) (16 clips) and the hand person boxes of [smoke test E](../2026-10-27-smoke-e-hi-vis/LOG.md).

### Result

| Id | Mark | Result |
|---|---|---|
| A1 | Truck box IoU at least 0.5 on every in-view hand sample but one, present on 90% of in-view frames, on at least 14 of 16 clips | **fail, 13 of 16.** Two clips have no in-view hand sample and count against the mark as written; on the 14 scorable it is 13 of 14. The real loss is a speeding truck, lost from 2 s while still in view. Median IoU 0.92 over 53 samples |
| A2 | At least 12 of 13 labelled pedestrians found | **pass, 12 of 13**; all 5 drivers also come back as "person", so the operator rule is still needed |
| A3 | "pallet racking upright" returns a narrow object on each of 5 collision clips | **fail, 0 of 5**: the concept returned nothing on any of the 26 clips |

One call with two concepts ("forklift. person") tracked one object only, so one concept per call is the form.
A comparison against the hand-prompted exhibit needs a renderer that did not exist yet, so it was not run.

SAM 3.1 from text alone is the strongest Meta-use result here: the truck on 13 of 14 scorable clips and 12 of 13 pedestrians, with no box drawn by anyone.
Its two gaps are a fast truck lost after 2 s and the upright concept returning nothing, so the structure strip stays hand-drawn in the site file and a fast truck needs a detector-seeded box.

## Cost

All 449 paid calls matched to ledger rows, 0 unmatched, 0 cache hits.

| Test | Calls | Ledger |
|---|---|---|
| 1 native video picker (70 racing, 52 forklift) | 122 | $0.76 |
| 2 predicate census (110 main, 60 second run, 38 bait, 14 withheld) | 222 | $4.77 |
| 3 SAM text tracking | 105 | $1.26 |
| Total | 449 | **$6.79 of the $12 cap** |

Test 2's first scan-rule calls cost about $0.06 each, so its own ceiling was raised from $5 to $8 before any arm reached it; the $12 cap was unchanged and no mark changed.

## What the design takes from this

1. Native video on Spark Open samples a fixed 1 frame a second.
   It is not the locator in either domain; it can rule or describe inside a window a script has opened.
2. On forklift clips the script owns the second.
3. SAM 3.1 from text alone gives the truck and the people with no hand box; the structure strip stays hand-drawn.
4. A closed grammar keeps compiled rules faithful to the field list and numbers, but the model cannot decide judgeability, so each pack keeps a hand route key.

## What it does not prove

- Nobody checked by eye which racing events are on screen, so "inside the bound" is a lower bound.
- One prompt, one effort level, one racing encode; two input rates (10 and 24 fps) both read as 1 fps.
- 26 AI-made forklift clips, 5 s each; the upright result is one phrase, and other wordings were not tried.
