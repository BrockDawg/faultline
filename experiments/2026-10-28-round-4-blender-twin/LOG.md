# Round 4: the Blender twin (28 Oct 2026, overnight)

## Question

When a Blender aisle emits its own per-frame truth, how much of each forklift metre (speed, person-to-truck separation, fork-tip contact) is error from the hand floor marks, how much from the measuring method, and how much from perception (SAM masks, DETR boxes)?

Spend caps in code: $1.00 of SAM through the metering proxy, $5 of Modal.

## Pre-registration (committed before the first render)

### The scene and the truth

- One Blender scene (Blender 4.5.15 LTS, headless): an aisle with racking both sides, yellow aisle lines, a cross aisle, a back wall, and a fixed CCTV-like camera at 3.2 m with a 60 degree field of view.
- A procedural counterbalance truck, exactly 3.0 m overall (2.0 m body plus 1.0 m tines) by 1.15 m, with mast, overhead guard, wheels and a seated operator.
- People: procedural mannequins (capsule limbs, head, hi-vis vest), walking or standing.
  No CC0 human model could be downloaded that night, so whether DETR and SAM see these mannequins is itself a finding.
- The truth schema was fixed before the first render: per frame, the truck footprint, corners, fork tips, rear-centre, signed speed and projected boxes; each person's footpoint, box and floor distance to the truck; fork-tip distance to the structure; the camera matrices and floor homography; the contact frame.
- 13 clips: six speeds (0.5, 1.0, 1.5, 2.0, 2.5, 3.5 m/s), three crossings that stop the forks 1.0, 2.0 and 4.0 m short of a walker, a reversing pass with a spotter and one without, one fork-tip contact on a rack post at 1.2 m/s, and a near pass that stops 0.3 m short.
  Plus one survey still (truck parked, a 1.2 x 1.0 m pallet on the floor) for the floor marks.
- Eevee, 1280 x 720, 24 fps, 121 frames, then x264 CRF 23 with fixed-seed grain, so the chain reads compressed video like CCTV.

### The measuring chain (inherited, not tuned)

- Floor plane, speed and contact from [smoke test I](../2026-10-27-smoke-i-floor-plane-speed/LOG.md): the truck footpoint is the bottom-centre of the truck box, sampled once a second, and peak speed is the largest step.
- Separation from [smoke test J](../2026-10-27-smoke-j-floor-distance-ruling/LOG.md): a person's footpoint to the truck's floor polygons.
- The tracker and operator rule from [smoke test K](../2026-10-27-smoke-k-tracker/LOG.md), unchanged.
- Two contact rules: the inherited rear-footpoint strip (0.30 m), and a front-point rule fixed now (front point 3.0 m ahead along the travel direction, within 0.15 m of a structure base for 3 frames in a row).

### Arms

| Arm | Floor homography | Truck and person inputs | What its error is |
|---|---|---|---|
| A, method | true | truth boxes | the method alone |
| B, hand floor marks | hand, from blind marks on the survey still | truth boxes | A plus the floor marks |
| B2, hand chain | hand | hand-drawn truck boxes and floor quads | B plus hand-drawn boxes |
| C, perception | true | SAM 3.1 truck masks, DETR person boxes through the tracker | A plus perception |
| D, deployable | hand | as C | everything together, reported only |

The floor marks were placed blind by four markers (Claude, each in its own session), on the survey still with a 50 px grid, told only the truck and pallet sizes.
Arm B uses the first marker's truck footprint; the other three and the pallet marks are the scatter.
Truck boxes were drawn on sheets under opaque ids, with no clip name, speed or truth.
Two held-out floor points are never marked and test the hand homography.

### Pass marks

19 marks, among them: held-out points within 2% through the hand homography (P1); method speed within 5% on 6 of 6 ladder clips (A1); method separation within 0.20 m (A3); the front-point rule fires within 3 frames of the truth contact and not on the near pass (A5); hand-mark speed within 10% on 4 of 6 (B1); perception speed within 20% (C1), separation within 0.50 m (C2), coverage at least 90% (C3) and contact (C4); the tracker drops the operator (K1) and keeps the walkers and the spotter (K2); two scoring runs byte-identical (R1).

## Deviations

- The survey pallet moved out from behind the truck, and the crossings were rebuilt so the truck faces the camera with its forks leading; in the first version the truck body hid the walker.
- SAM's text prompt "forklift" returned nothing on all 13 clips and on the survey image, so every clip took the pre-registered fallback: a box prompt on frame 0 from the hand-drawn box.
- The tracker marks use the truth truck box for the operator rule, because one hand box per clip cannot follow a moving truck.
- DETR ran on Modal CPU containers, not locally, after the local run stalled; same pinned weights, same versions, one thread, score 0.9, and every frame's sha256 matched a local decode.
- Added after the DETR result was read, reported only: one SAM "person" call on each clip with a walker or spotter.

## Result

11 of the 19 marks hold.
The two scoring runs are byte-identical.

| # | Mark | Result |
|---|---|---|
| P1 | held-out points within 2% | **fail**: 5.5% and 12.1% (the best of the eight hand homographies gives 9.8% and 0.9%) |
| A1 | method speed within 5% | pass: +3.9% on every clip |
| A3 | method separation within 0.20 m | pass: +0.08, +0.11, +0.12 m |
| A5 | front-point contact rule | **fail**: fires at frame 75 against truth 84, and fires on the 0.3 m near pass |
| A6 | reversing speed within 5%, toward the camera | pass: +3.9% on both |
| B1 | hand floor marks, speed within 10% | pass: 6 of 6, worst -3.1% |
| B2 | hand floor marks, separation within 0.30 m on 2 of 3 | pass: 2 of 3 (the 4 m crossing reads 3.71) |
| B3 | hand floor marks, contact | **fail**: fires 19 frames early and on the near pass |
| H1, H2 | hand chain, speed and separation | pass: 6 of 6 (worst -3.7%), 3 of 3 |
| C1 | perception, speed within 20% | pass: +3.7% to +5.8% |
| C2 | perception, separation within 0.50 m | **fail**: no reading on the 1 m crossing (DETR lost the walker) |
| C3 | perception coverage | **fail**: SAM holds the truck on every frame, DETR finds the walkers on 13, 14 and 21 of 121 frames and the spotter on 0 |
| C4 | perception, contact | **fail**: silent on the contact clip, fires on the near pass |
| K1 | tracker drops the operator | **fail, empty**: DETR never boxes the seated operator |
| K2 | tracker keeps walkers and spotter | **fail**: 2 of 4; the 1 m walker is dropped as an "operator" because its box centre sits inside the truck box |
| A2, A4, R1 | the 2.2 m/s and 3 m lines split their clips; byte-identical | pass |

### Where the error comes from (median absolute error)

| Source | Speed | Separation at frame 72 |
|---|---|---|
| Method (A against truth) | 3.9% | 0.107 m |
| Hand floor marks (B) | 2.0% from truth, because its scale error cancels part of the method's bias | 0.076 m |
| Hand-drawn boxes (B2) | 1.1% from truth | 0.136 m |
| Perception (C against A) | 4.2% (SAM box prompt) | DETR: no reading on 1 of 3 |

- The largest single error is the method, with one cause.
  The truck box's bottom edge is the counterweight's underside, 0.12 m above the floor.
  Projecting it as if it were on the floor scales every distance by 3.2 / (3.2 - 0.12) = 1.039, the +3.9% on every clip.
- The same lift puts the inferred fork tip about 0.4 m too far forward, so the front-point rule fails on perfect inputs: a 0.15 m strip cannot sit inside a 0.4 m bias.
  The inherited rear strip never fires on either clip, as predicted.
- Floor marks matter as much as the method only when a marker guesses the hidden far corners badly.
  Measured click error: 2.9 px RMS on the visible pallet corners, 9.9 px on the truck's near corners, 17.1 px on its hidden far corners.
  One marker's far corners alone turn 3.5 m/s into 7.1.
- Hand-drawn boxes on rendered frames land within 1 to 3 px of truth; crisp rendered edges flatter them, so this does not transfer to real CCTV.
- SAM tracks the truck on every frame once given a box, but does not call this procedural truck a "forklift" (13 of 13 text prompts empty).
  DETR at 0.9 barely sees cylinder mannequins, so this run does not test DETR on people.
  SAM "person" held the walker on 60 of 61 frames on each crossing and found nothing on the spotter clip.
- The operator rule drops a walker who crosses in front of a truck facing the camera, which removes a pedestrian from the evidence, the dangerous direction, and would happen on real footage too.

### Uncertainty budget check (reported)

The measured hand-click sigma is 10.1 px, close to the 10 px assumed earlier.
A 95% interval from 500 draws of each marker's clicks covers the truth on 42 of 44 speed and separation readings (95.5%, Wilson 0.85 to 0.99).
The interval is wide where it needs to be, so read the interval, never the point.

## Cost

- SAM through the metering proxy: $0.3685 (one image probe, 13 text-prompt videos, 13 box-prompt videos, 4 "person" videos), under the $1.00 cap in code.
- Modal: two DETR runs, $0.3011 in all, under the $5 cap; the two runs gave byte-identical boxes.
- Renders on a local GPU and the blind markers on my Claude subscription: $0.

## What it does not prove

- One rendered camera, one truck shape, one lighting setup, no lens distortion, no blur.
- The +3.9% belongs to this camera height and this counterweight clearance; the direction holds everywhere, the size changes with each site.
- n is 3 to 8 per mark, so these are per-clip checks, not rates.
- The person results test mannequins, not people.

## Needs

- Fix the footpoint before any metre ships, then re-run the contact rule from the recorded truth and masks at $0.
  That ran the same day: see [the footpoint clearance fix](../2026-10-28-round-4-footpoint-clearance/LOG.md).
- Floor marks should use visible floor features, or carry the interval.
- The operator rule needs more than box-centre-in-truck-box before it drops anyone.
- A human mesh with clothes and skin before the person half of perception can be tested.
