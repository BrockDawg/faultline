# Round 4: the forklift metre (28 Oct 2026, overnight)

## Question

Can the forklift side quote its measurements in metres, and if not, what does it speak in?
Five tests, all pre-registered and committed before the first run of any of them:

| # | Test | Cost |
|---|---|---|
| 0 | Is the synthetic truck 3.0 by 1.15 m through the floor plane? (aspect audit) | $0 |
| 1 | Uncertainty budget: do the speed and distance bands stay clear of the site lines? | $0 |
| 2 | Walking speed as a free scale witness | $0 |
| 3 | Is SAM 3.1 deterministic on identical bytes? | paid |
| 4 | A script verdict over a banded fact sheet, against Spark Open and Spark 1.3 handed the same sheet | paid |

Spend cap $4.00 through the metering proxy, held in code: before each call the meter added the call's worst-case price to what the experiment had spent and refused the call if that passed the cap.
Sub-caps: test 3 $1.10, test 4 $2.80.

## Shared inputs

- 26 synthetic clips: the 16 fixed-camera clips and the 10 round-2 aisle clips.
- The key is the folder label, with the rule each breach clip is expected under: 10 compliant, 16 breach.
  Label doubts written before any run: 04's truck travels load first up the aisle, so its "no spotter" label may not be a reversing breach; 05 drives forward; 33's prompted person never appears.
- Speed is not one of the four site rules, but 06 and 36 are labelled speed breaches, so the pack here is the four site rules plus a site speed limit at 2.2 m/s.
- Site values: separation 3.0 m, speed 2.2 m/s, truck 3.0 x 1.15 m.
- Two independent hand-marked floor planes per camera: plane I from [smoke test I](../2026-10-27-smoke-i-floor-plane-speed/LOG.md) (the primary) and plane J from [smoke test J](../2026-10-27-smoke-j-floor-distance-ruling/LOG.md).
  Both are built from the truck footprint, so the truck reads its assumed size at the reference frame by construction.
- Truck: SAM 3.1 video masks at 12 fps; person: pinned DETR ResNet-50 tracks through the [smoke test K](../2026-10-27-smoke-k-tracker/LOG.md) tracker.
- Fork-end points and structure bases were hand-marked blind under opaque ids, then checked by a second marker; none was plainly wrong.
- Frames, masks and replies stayed private.

## Deviations (named before any result was read)

- Test 3's first pass (the 16 missing masks) ran before tests 0 to 2, because they need those masks.
- The idle clip 40 has no truck, so 25 clips carry a mask.
- All 10 round-2 clips sit within 1.63 px of clip 04's camera, so they use 04's planes unchanged.
- Two code bugs were fixed before scoring, each named in the private record; neither changed a threshold.

## Results

### 0. Aspect audit: the ratio cannot be read from one fixed camera

| Mark | Result |
|---|---|
| Ratio within 15% of 2.61 on at least 20 clips | **Fail: 0 clips.** No clip has both a side-on length and an end-on width reading |
| Aisle-camera length spread under 10% | **Not measurable:** every aisle clip is end-on |
| Two runs byte-identical | **Pass** (from the recorded masks) |

- Side-on lengths, through plane I: 3.80, 3.95 and 2.66 m on three clips (plane J: 2.99, 4.11, 3.91 m).
- The assumed 1.15 m width holds to about 10% on the aisle camera through plane I (1.01 to 1.11 m); plane J reads it 15 to 30% wider.
- The fail rule applies: the scale term in tests 1 and 4 becomes the robust length spread across clips, 5.89%.
  That rests on three lengths whose plain spread is about 19%, so it understates the scale doubt.

### 2. Walking speed: every walker reads two to four times too slow

| Mark | Result |
|---|---|
| At least 70% of walking tracks at 1.0 to 1.7 m/s through plane J | **Fail: 0 of 10** (Wilson 0 to 28%); plane I also 0 of 10 |
| Per-camera factor 0.8 to 1.25 on at least 70% of cameras | **Fail: 0 of 8**; factors 2.1 to 4.1 |
| Planes I and J within 25% on every camera | **Fail as written:** 7 of 7 cameras with both agree (ratio 0.87 to 1.17), but the aisle walker never passes 0.3 m/s through plane I |
| Two runs byte-identical | **Pass** |

- Median walking speeds run from 0.34 to 0.67 m/s; the implied step length is 0.19 to 0.50 m on 8 tracks.
- The two planes agree here, so the hand marks are not what makes the walkers slow.
- Either the floor scale is two to four times short, or the generated people move in slow motion.
  A scale that short would make the truck 6 to 12 m long beside people of normal size, so slow generated motion is the likelier reading; this test cannot tell them apart, and [the Blender twin](../2026-10-28-round-4-blender-twin/LOG.md) can.
- By the fail rule fixed before the run, the truck scale is uncorroborated, and every forklift metre carries a band of at least ±30%.

### 1. Uncertainty budget: the bands do not hold a metre against the site lines

500 draws per clip, perturbing the floor points (10 px), the scale (5.89%) and every footpoint by its measured jitter (SAM truck 3.6 px x, 1.8 px y; DETR person 2.4 px x, 4.2 px y).

| Mark | Result |
|---|---|
| Every value has a finite interval | **Pass** |
| Two runs byte-identical | **Pass** (from the recorded masks) |
| Width never shrinks as sigma rises | **Fail:** 78.6% monotone (percentile noise at 500 draws) |
| Footpoints outside the marked quad carry wider intervals | **Fail: 3 of 7** clips |
| 36 proven over 2.2 m/s, 34 and 35 clear, 39 proven under 3 m | **Fail.** 36 reads clear at 1.91 m/s (1.68 to 2.17); 39 reads clear, no one on foot within 3 m while the truck is proven moving |
| Coverage of the 95% interval at least 90% | **Fail.** Plane J's value inside plane I's interval on 63% of 102 at 10 px; 89% even at 30 px |
| At most 2 of 9 aisle clips not proven on speed | **Pass: 0** |
| No flip among rulings more than 2 SD from the line | **Pass:** 29 such rulings, 0 flips under 16 perturbed planes |
| 36's full speed interval under 30% of its median | **Pass:** 25% |

| Clip | Label | Peak m/s | 95% interval | Verdict |
|---|---|---|---|---|
| 34 | slow | 1.18 | 0.98 to 1.40 | clear |
| 35 | normal | 1.34 | 1.14 to 1.57 | clear |
| 36 | fast | 1.91 | 1.68 to 2.17 | clear |
| 06 (other camera) | speeding | 3.66 | 3.20 to 4.58 | proven |

- The order holds (34 < 35 < 36), so speed works as an ordinal: a ranking, not a measured quantity.
- The two planes disagree by more than any click error up to 30 px covers, so the error is systematic, not random.
- Metre or ordinal, by the rule fixed before the run: 12 of 42 values have a band clear of the line with both planes within 20%, but the walkers fail on every camera, so **0 values may be quoted in metres**.

### 3. SAM determinism: SAM 3.1 is not deterministic on identical bytes

Each of the 25 video requests was resent with one added metadata field so the proxy cache missed; the bytes and the box prompt were identical.

| Mark | Result |
|---|---|
| IoU 1.000 and identical footpoints on every repeat | **Fail: 0 of 25 identical.** Mean IoU 0.9970 to 0.9997, worst frame 0.956; the rear footpoint moves 0.5 to 2 px on 23 clips and 14.4 px on one |
| Remux to mkv and mov: the same class | **Same class:** 0 of 10 identical |
| CRF 18 transcode: mean IoU at least 0.95 and footpoint within 2 px on 4 of 5 | **Fail: 2 of 5.** IoU 0.98 to 0.99, but the footpoint moves 3.5, 6.2 and 12.5 px on three clips |
| CRF 28 (reported) | Mean IoU 0.976 to 0.987, footpoint up to 7.5 px |

- Every "byte-identical" result in this experiment means "byte-identical from the recorded masks".
  The masks of record ship with every ruling, and a replay runs from the record.
- A site that re-encodes its export can move a footpoint 12.5 px at CRF 18, which argues for a minimum export quality in the site file.

### 4. Who writes the verdict: script against two models

The sheet: every clause of the five rules as a measured field with its band, and a three-way verdict (breach, clear, cannot judge).
Arm A is the script over the sheet; arm B is Spark Open (two runs); arm C is Spark 1.3 (one run); each model got the rule text, the sheet and five frames.
The verdict-seat rule, fixed before any arm reported: a model may hold the verdict only with 0 false breaches on the 10 compliant clips and at least the script's right rulings plus 3, and any invented quantity disqualifies it.

| Mark | Result |
|---|---|
| Script: 0 of 10 compliant clips ruled breach | **Fail: 2 of 10** (05 and 31, both separation) |
| Script: at least 13 of 16 breach clips right | **Fail: 7 of 16** (Wilson 23 to 67%) |
| Script: cannot judge on at most 4 of 26 | **Fail: 7 of 26** |
| Script: two runs byte-identical | **Pass** (from the recorded masks) |
| All paid calls finish `stop` | **Pass:** 78 of 78 |

| Arm | False breach (of 10) | Right (of 26) | Wrong rule | Missed | Cannot judge | Invented quantities | Cost per clip |
|---|---|---|---|---|---|---|---|
| A, script | 2 | 11 | 3 | 3 | 7 | none | $0 |
| B run 1, Spark Open | 2 | 14 | 5 | 2 | 3 | "50 %" on 3 clips | $0.026 |
| B run 2, Spark Open | 2 | 15 | 5 | 3 | 1 | "50 %" on 6 clips, "76 %" on 31 | $0.025 |
| C, Spark 1.3 | 2 | 13 | 5 | 2 | 4 | "50 %" on clip 10 | $0.019 |

- **Verdict seat: the script.** No arm has 0 false breaches, and the invented quantities would disqualify every model arm anyway.
  The model writes evidence text only.
- Both false breaches fire the same rule in every arm: a vested person within 1 m of a moving truck (05 at 0.90 m, 31 at 0.63 m), and the separation rule exempts only a stopped truck or a dock zone.
- The models gain over the script on four compliant clips where the script reads cannot judge, but on two of them they ruled clear on intervals that straddle the line, which the pack forbids.
  A breach not proven gets read as clear: a wrong-pass risk, not a better reading.
- A separate grader read the frames of the 17 clips where any arm disagrees with the key.
  It named the fixes as fields, not models: a spotter exemption in the separation rule, the truck's side and rear measured against structures, a person detector that does not miss clip 37, and a guard against degenerate plane draws.
  It judged three keys wrong (04, 05, 37) and seven doubtful.
  The score stands against the frozen key.

A later label review of the frames changed two keys: 04 to compliant (the truck never reverses) and 05 to a separation breach (a walker ends about 1 to 1.5 m from the moving truck).
37 stays compliant, with a person on foot far up the aisle.
Nothing here was rescored on the new keys.

## What it shows

1. Forklift numbers are ordinal on this synthetic set: the walkers read two to four times slow on every camera and the two hand planes disagree beyond any click error, so no sheet value may be quoted in metres.
2. SAM 3.1 is not deterministic on identical bytes, so every replay runs from the recorded masks.
3. The script over a banded sheet does not clear the bar, and neither Spark model does better on false breaches.
   The verdict stays with the script, and the row reads cannot judge, with the missing field named.

## Cost

$2.570 of the $4.00 cap, from the ledger: test 3 $0.747 on 100 SAM calls, test 4 $1.823 on 78 model calls.
Tests 0, 1 and 2 cost $0.

## What it does not prove

- No clip has a true metre: coverage compares two hand planes, not a truth.
- Synthetic people and trucks, one detector, no real footage.
- The round-2 person detections ran once; a second run for the hash check did not complete, so their byte identity is unproven.
