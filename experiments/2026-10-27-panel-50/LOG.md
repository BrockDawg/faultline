# The steward panel against a single call on 50 cases (27 Oct 2026)

Status: run on 27 Oct 2026.
The primary mark is not met: the panel got 20 of 50 and the single call 18, a gap of 2 where the mark needed 5.
Everything under "Fixed before the first run" was written before the case selection or any model call ran.
Three amendments were made before any model call, and no model output had been seen when they were made.

## Question

Does a prosecutor, defence and judge panel rule more often like the human steward than one steward call, on 50 cases and not 5?
[The steward panel](../2026-10-27-steward-panel/LOG.md) saw single Spark 2 of 5 and the Spark panel 3 of 5, which is a lead and not a proof.

## Fixed before the first run

### Cases

- Pool: the development split of the steward-stream corpus only; the held-out items stay untouched.
- A case is eligible when its label source is `spoken`, its drafted verdict is `penalty`, `racing_incident` or `no_action`, its drafted confidence is 0.6 or more, its window is 20 to 120 s long, and its video is on disk.
- Seeded rule: rank eligible cases by `sha256` of a fixed seed and the case id, ascending.
  Walk the ranked list once per verdict and accept a case unless its video already has 3 accepted cases or its window overlaps an accepted window in the same video.
  Quotas: 20 `penalty`, 15 `racing_incident`, 15 `no_action`.
- The quotas are stratified because the development split is 51% penalty, and a model that always says "penalty" should not score 51% for free.
- The chosen set uses opaque case ids; the map to corpus ids is kept with the private record.

### Input to both arms

- 16 frames at evenly spaced seconds across the window, 1024 px wide, each labelled with its video second.
- The same neutral header on every call.
  There is no driver report in the corpus, so the header says the images are frames of a stewards' review segment and asks for a ruling on the main incident.
- The sporting code line is the generic one from [Discovery 3](../2026-10-26-discovery-3/LOG.md).
- The label text, the caption text and the corpus ids are never in a prompt.
- Temperature 0, output limit 16,000 tokens, a separate case reference on every call so the proxy cache cannot answer.

### Arms

| Arm | Model | Calls per case |
|---|---|---|
| S: single call | Spark 1.3 (`muse-spark-1.3`) | 1 |
| P: panel | Spark 1.3 as prosecutor, defence and judge (the steward panel's prompts, setup A) | 3 |

A Spark Open panel was optional, left for me to approve, and did not run.

### Scoring

- A call is correct when its verdict equals the drafted label's verdict exactly.
- A call with no parsed verdict, a verdict outside the three, or a finish other than `stop` counts as wrong and stays in the denominator of 50.
  A wrong pass is worse than a wrong fail, so nothing is retried to rescue a case; one retry on an HTTP error is allowed, once, and logged.
- The label is a model-drafted reading of the reviewer's spoken words, only partly reviewed by me.
  Agreement here means agreement with the drafted label, not with a verified human steward decision.

### Pass marks

1. Primary: P correct is at least S correct plus 5 cases (10 points of 50).
   If not met, the panel is dropped from the design as a general tier.
2. Validity: each arm returns a parsed verdict with `finish: stop` on at least 45 of 50 cases, or the primary mark is reported invalid.
3. Stratum guard: neither arm gets more than 60% of its correct cases from one verdict class, or the result is reported as "reads the prior, not the video".

### Cost and limits

- Expected about $10 for both arms, from the steward panel's per-case cost on 22 frames.
- Every call went through the metering proxy, and the script stops at a cap of $11 for both arms together.

## Amendments, all before any model call

1. The first rule had a confidence floor of 0.8, which found a pool of 21 cases and could not fill 50.
   That floor was written without counting the pool.
   The floor became 0.6, every kept label, with a new seed so the set is not a trimmed version of one already looked at.
   A new reported figure, with no mark: correct per confidence band.
2. One chosen case's window ended 0.2 s after the end of its video file.
   A case is now eligible only when its window ends inside the video; the seed, quotas and ranking are unchanged, so the next case in rank order replaced it.
3. One frame per video showed all 27 videos are one league's review stream with the same layout.
   The race-control software window, top left, prints words such as "NO ACTION" and "RACING INCIDENT" beside driver names, and penalty-point text and viewer chat sit across the top.
   Both arms now see frames with two black boxes, the top 40% of the picture and the top-left 60% by 57%, set in proportions of the frame and the same on every frame.
   The replay pane and the small onboard pane stay.
   Two masked frames were checked: no text was left in the visible area except the stream's own logo and caption.
   The cost is that the replay's top-left corner can be covered in layouts where the pane starts under the window.

## Checks before the run

- Selection: 50 cases (20 penalty, 15 racing incident, 15 no action) from a pool of 86, over 27 videos; 40 at confidence 0.6 and 10 at 0.8.
- Dry run: all 800 masked frames cut, with no model call.
- Known weakness: some windows show a title card or a non-replay view for part of their length, and those cases count wrong in both arms.

## Result

### Arm S

- 50 of 50 calls returned `finish: stop` and a parsed verdict.
- Correct: 18 of 50 (36%).
- Verdicts given: 23 penalty, 23 no action, 4 racing incident.

| Label | penalty given | racing incident given | no action given |
|---|---|---|---|
| penalty (20) | 8 | 1 | 11 |
| racing incident (15) | 11 | 1 | 3 |
| no action (15) | 4 | 2 | 9 |

- Cost: $1.64 by the proxy ledger.
- The probe ledger stood at $20.09 after arm S, past its $20 cap, so the run stopped and waited for my call.
  I said to run P, and P ran with no refusal.

### Arm P

- 150 of 150 calls returned `finish: stop`; all 50 judges returned a parsed verdict.
- Correct: 20 of 50 (40%).
- Tokens: about 3,300 per counsel call and about 3,100 per judge call.

| Label | penalty given | racing incident given | no action given |
|---|---|---|---|
| penalty (20) | 4 | 2 | 14 |
| racing incident (15) | 3 | 7 | 5 |
| no action (15) | 1 | 5 | 9 |

### Marks, as written before the run

| Mark | Result | Met |
|---|---|---|
| Validity: 45 or more parsed verdicts with `finish: stop` in each arm | S 50, P 50 | yes |
| Stratum guard: no verdict class over 60% of an arm's correct cases | S 50% (no action), P 45% (no action) | yes |
| Primary: P correct at least S correct plus 5 | P 20, S 18, gap 2 | **no** |

**The primary mark is not met**, so the panel is dropped from the design as a general tier.

### Other figures (no mark)

| | S | P |
|---|---|---|
| Correct of 50 | 18 | 20 |
| Paired | both right 12, only S 6, only P 8, neither 24 | |
| Penalty cases right (of 20) | 8 | 4 |
| Racing incident cases right (of 15) | 1 | 7 |
| No action cases right (of 15) | 9 | 9 |
| Right on 0.6-confidence labels (of 40) | 15 | 17 |
| Right on 0.8-confidence labels (of 10) | 3 | 3 |
| Cost by the priced calls | $1.64 | $4.58 |

## What it shows

- Both arms sit at or under what a constant answer scores on this set.
  Always "penalty" would be right on 20 of 50 (40%); S got 36% and P got 40%, so neither read the video well enough to beat a guess.
- The two arms fail in opposite ways.
  S leans to "penalty" and "no action" and almost never says "racing incident" (1 of 15 right).
  P leans to "no action" and "racing incident" and misses penalties (14 of 20 penalty cases ruled no action).
  The panel moved errors between classes more than it removed them.
- The gap of 2 cases is inside what 50 cases can tell apart: 8 cases went P's way and 6 went S's way.

## Cost

| Item | Dollars |
|---|---|
| Arm S | 1.64 |
| Arm P | 4.58 |
| Total, priced calls | 6.22 |

- Expected about $10; the run cost less because 16 frames cost less than the steward panel's 22.
- The proxy ledger moved by $5.64 over arm P against $4.58 priced, because other runs spent through the same proxy at the same time.

## What it does not prove

- It does not show the panel is useless.
  It shows that on these 50 cases, with these masked frames and no report text, it was not 10 points better.
- Where the drafted label is wrong, a correct ruling counts as a miss in both arms.
  The 0.8-confidence labels scored 3 of 10 in both arms, too few to say whether they are cleaner.
- The input is one league's stream with the race-control window blacked out, and the replay pane is small, so contact in a corner of the pane can sit at a few pixels.
  The steward panel already found that no role can argue for a touch the frames do not show.
- No driver report was given, so the model had to pick the incident itself, which the five-clip panel did not ask of it.
- One run per cell at temperature 0, with no repeat.

## Needs

- If the panel stays in the design, it stays as an appeal tier on cases where the single call and a human steward disagree, and that needs its own test on disagreements only.
- I will review a sample of the 0.6-confidence labels before any agreement figure from this corpus is quoted.
- Check whether a higher-resolution crop of the replay pane changes S and P before the corpus input is ruled unusable.

## Files

The selection and panel scripts, the selection, the per-arm results and the raw replies are kept with this experiment's private record and never enter git.
