# OCR on number crops, snapped to the closed set (27 Oct 2026)

It builds on [smoke test A](../2026-10-27-smoke-a-closed-set-identity/LOG.md) (the snap rule and the 8 m closed set) and the [Discovery 3](../2026-10-26-discovery-3/LOG.md) answer key.
The first run used scripts and the CPU only, for $0.
A retest with SAM boxes cost $0.105 of SAM, once I approved it.
Both runs failed.

## Question

Does PaddleOCR on the detector's car crops, snapped to smoke A's closed set, name the key partner without naming a wrong car?

## Marks fixed before the first run

### Why "8 of 10" becomes "5 of 6"

Smoke A scored 10 key cases that have a named partner.
Video is on disk for only some of them, and a case needs a video offset with an error of 2 s or less to place a frame.

| Report | Offset error | In this test |
|---|---|---|
| 9 | 0.5 s | yes |
| 13 | 1 s | yes |
| 14 | 1.5 s | yes |
| 1 | 1 s | yes |
| 2 | 1 s | yes |
| 46 | 2 s | yes |
| 10, 18 | | no: the key names no partner |
| 11, 48, 23, 16 | | no: no video on disk |

The denominator is 6, not 10, and the planned 80% scales to 5 of 6.
This deviation is forced by the footage, not chosen.

### Procedure

1. For each case, 7 frames, one a second from contact minus 3 s to contact plus 3 s, cut with ffmpeg from the source clips.
2. Detector: `facebook/detr-resnet-50` as pinned in [smoke test H](../2026-10-27-smoke-h-detector-ruling/LOG.md), CPU, classes `car` and `truck`, score at least 0.5.
   Each box is padded 10% and the crop is enlarged 3 times (cubic) before OCR.
3. OCR: PaddleOCR defaults on each crop.
   A read is kept when it is 1 to 3 digits after non-digits are removed and its text score is at least 0.5.
4. Snap: smoke A's `snap()` unchanged (nearest by digit edit distance; a tie or a distance over 1 is refused).
   Candidates are the 8 m set over contact plus or minus 3 s, plus the camera car, because the OCR does not know which car it is reading.
5. Case answer: count the snapped numbers over the 7 frames, leave out the camera car's own number, and take the most-voted number.
   A tie or no votes is `none`.

### Pass marks

1. At least 5 of the 6 cases answer the key partner.
2. No case answers a wrong car: `none` is not wrong, and a number that is neither the partner nor the camera car is.
3. Two runs give a byte-identical result file.

Reported, not scored: crops found, crops with a kept read, kept reads that snap, and a control where each case's reads are snapped against another case's set.

## Method as run

- The PaddleOCR 3.7.0 default recognition model is `PP-OCRv6_medium`, not v5 as the marks said; no setting was tuned.
- Paddle 3.3.1's oneDNN path crashed on this CPU, so the one change is `enable_mkldnn=False`, which changes speed, not the reads.
- DETR's weights hash was asserted against smoke H's pin (`830f5e2e…`).

## Result

| Mark | Needed | Got | Verdict |
|---|---|---|---|
| 1. Cases answering the key partner | 5 of 6 | 2 of 6 (1 of 6 real, see below) | fail |
| 2. Cases answering a wrong car | 0 | 0 | pass |
| 3. Two runs byte-identical | yes | yes: a fresh pass of frames, detector, OCR and scoring gave the same result file and the same boxes and raw reads | pass |

| Report | Camera car | Key partner | Crops | Kept reads | Case answer | What was read |
|---|---|---|---|---|---|---|
| 9 | 555 | 959 | 11 | 6 | none | `555` five times (the camera car, score 0.79 to 1.00); `959` never |
| 13 | 26 | 44 | 11 | 1 | 44 | `44` once (score 1.00); a sponsor word on every other crop |
| 14 | 32 | 70 | 20 | 36 | 70 | scored as the partner, but spurious: see below |
| 1 | 111 | 44 | 34 | 3 | none | `0`, `5`, `5`; none snaps |
| 2 | 111 | 22 | 18 | 3 | none | `8`, `5`, `44`; `44` is not in this set, so it is refused |
| 46 | 334 | 01 | 31 | 1 | none | `60`; livery text on five crops, no number |

Totals: 42 frames, 125 crops, 47 crops with any text, 17 crops with a kept digit read, 19 kept reads that snapped to anything.
Control: 0 snaps to the other case's partner, so the snap did not invent a partner from nothing here.

### The case 14 answer is not a real read

DETR boxed the whole 1280 by 720 frame as a `car` in three frames, so the OCR read the on-screen display: the leaderboard, lap counters and the speed read-out.
Three of those digit strings (`10`, `76`, `79`, all in one frame) are one digit away from `70`.
The set for that case holds two cars, so the snap took them for the partner.
The mark was written on case answers, so it counts this case as a pass, 2 of 6.
No real car number was read in that case, so the count from real reads is 1 of 6 (report 13, a single read).
Mark 1 fails on either count.

## Retest A: SAM boxes in place of DETR boxes

The cause of the first failure was the crops, so the retest changes only where the crops come from, and adds a half-frame gate.
The first result stands unedited.

Marks, fixed before the first paid call: marks 1 to 3 unchanged (mark 3 reruns crops, OCR and scoring from the recorded SAM replies, because SAM itself cannot be pinned), plus:

4. This retest's own SAM spend stays under $0.20.
5. A read counts only if its box covers 50% of the frame or less.

Procedure: the same 42 frames as JPEG, one `sam-3.1` image call per frame with the prompt `race car`, through the metering proxy.
Boxes under 24 px wide and boxes over half the frame are dropped; everything after that is the first run's procedure unchanged.

| Mark | Needed | Got | Verdict |
|---|---|---|---|
| 1. Cases answering the key partner | 5 of 6 | 2 of 6 (reports 9 and 13) | fail |
| 2. Cases answering a wrong car | 0 | 2 (reports 1 and 46, both `18`) | fail |
| 3. Two runs byte-identical | yes | yes | pass |
| 4. Own SAM spend under $0.20 | yes | $0.105, 42 calls at $0.0025 | pass |
| 5. No read from a box over half the frame | yes | 0 boxes over the gate | pass |

SAM returned 123 boxes on the 42 frames; 4 under 24 px wide were dropped, leaving 119 crops.
60 crops had any text, 28 had a kept digit read, and 15 kept reads snapped.

| Report | Camera car | Key partner | Case answer | What drove it |
|---|---|---|---|---|
| 9 | 555 | 959 | 959, correct | one real read, `959` at score 0.999 on a crop of the car behind, in the contact frame; the second vote came from a race-control chat line naming car 959, which is on-screen text, not a car number |
| 13 | 26 | 44 | 44, correct | the same single `44` read as in the first run |
| 14 | 32 | 70 | none | one stray `4`; the first run's pass was spurious, and the gate removed it |
| 1 | 111 | 44 | 18, wrong | SAM boxed leaderboard rows at the left edge as `race car`, and their digits (`8`, `10`, `18`) snapped to `18` |
| 2 | 111 | 22 | none | one `000` |
| 46 | 334 | 01 | 18, wrong | a `10` read from a box beside the cars, one digit from `18` |

Control: 1 snap to the other case's partner in each of 4 cases, so the snap finds a partner in the wrong set from noise alone.
That is the same weakness as the two wrong answers.

## What it shows

- Real reads of the partner's own number came in 2 of 6 cases, both where the car is large in frame (report 9 at the contact frame, report 13).
  Sharper crops did not help on reports 1, 2, 14 and 46, where the cars are small.
- The snap rule accepts a distance of 1, so with a set of two cars any two-digit string one digit from the partner snaps.
  Overlay text (leaderboard rows, lap counters, chat) is the main source of those strings.
- The model read plus the snap stays, and the snap needs a guard before it takes any OCR input: refuse one-digit reads, refuse reads from boxes inside the overlay rectangles, and refuse a one-digit snap on a short read (`10` to `18`, `8` to `68`).
  These were not tried here, because a rule tuned on 6 cases would be fitted to the answer.

## What it does not prove

- It does not test the OCR on a clean target: none of the six cases gives a crop of the partner that is large and sharp in every frame.
- Report 46 shows livery text and no number, and liveries can show numbers that are not the sim numbers; this test does not separate the two.
- Six cases, chosen because video is on disk; four of the ten smoke A cases have no video here.
- The report 9 read is one frame, and the contact frame came from the key's own second, not from a detector.
- The two-camera streams are not tested: they have no telemetry and no key.
- No stencil or door-number test: the synthetic forklift trucks carry no numbers.

## Cost

- First run: $0, CPU only, no GPU; frames and DETR 2 min 38 s, PaddleOCR 5 min 11 s.
- Retest A: $0.105 of SAM image calls, 42 ledger lines at $0.0025, matching the estimate line for line.
  PaddleOCR on CPU, 0 GPU minutes, no Modal run.

## Needs

- This route is closed as failed.
- A third try would need a fresh set of key cases with the partner large in frame, and the overlay guard above fixed before it runs.

## Files

The OCR script, the boxes and results of both runs and the SAM call records are kept with this experiment's private record.
Frames, crops, the raw OCR text and the raw SAM replies hold broadcast frames and never enter git.
