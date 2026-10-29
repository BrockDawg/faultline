# Smoke test I: floor plane and speed (27 Oct 2026)

Scripts only, no model, no paid call, $0.
The design it tests is pieces 5, 6 and 13 of [the forklift scan route](../../docs/forklift-scan-route.md).
It also replays [smoke test G](../2026-10-27-smoke-g-structure-contact/LOG.md) with the structure drawn on the floor.

All five marks hold, but mark 4 holds because the floor strip never reads contact on any clip, the two real collisions included, so it does not show the strip works.

## Question

1. Does a four-point floor homography, scaled by hand off a pallet or the truck's length, turn a truck's footpoint into a floor speed that ranks the speeding clip first and keeps the compliant clips under a fixed line?
2. If the structure is a strip on the floor at its base, instead of a zone in the image, do the five compliant clips in smoke G stop reading "touched"?

## Pass marks and rules (written before the first run, not changed after)

Clips: the 16 fixed-camera synthetic clips; the clips stay out of git.
Truck samples: frames 0, 24, 48, 72, 96 and 120 (t = 0 to 5 s, 24 fps, 121 frames).

| # | Mark | Fixed value |
|---|---|---|
| 1 | `speeding_forklift_06` has the highest peak floor speed of the 16 clips | strict: a tie fails |
| 2 | `speeding_forklift_06` peak speed is at or above the line | 2.2 m/s (5 mph) |
| 3 | Each of the five compliant clips has a peak speed under the line | 2.2 m/s, set before any speed was computed |
| 4 | Smoke G replay: none of those five clips has a truck footpoint inside a structure strip for 3 frames in a row | strip = within 0.30 m of the structure's base segment on the floor |
| 5 | Two runs give byte-identical output | SHA-256 of each output file |

All five must hold for the smoke to pass.
A clip with no truck on a sample gets no speed for the seconds around it.

- Truck footpoint: bottom-centre of the hand truck box.
- Speed for second k: floor distance between the footpoints at t = k and t = k + 1, in m/s.
  Savitzky-Golay smoothing needs more than 1 Hz, so it is not applied at this rate and is not tested here.
- Deceleration for second k: speed(k) minus speed(k + 1), printed with no mark.
- Homography: direct linear transform in numpy (no OpenCV) on four hand-marked floor points, floor frame in metres.
  A round trip on a known homography returned the floor points to 6 decimals.
- Scale: a pallet (1200 x 1000 mm) where one lies on the floor, else the truck's own footprint (3.0 m long, set before the run, and 1.15 m wide, a second assumption), else a wider floor rectangle sized from the truck in the same clip.
- Hand marks: four floor points, six truck boxes per clip and, for smoke G's ten clips, two base points per structure, all frozen before the first run.
  They were drawn by four separate Claude sessions on frame sheets with the clip names hidden behind opaque ids, so no mark could follow a label.
  Where the frame edge cuts the rear of the truck, the box was extended to the estimated rear and flagged.
- Scale sources as marked: the truck's footprint on 13 clips, a floor pallet on 1 (`bump_guard_cctv_28`, small and far, so poorly conditioned), a floor rectangle sized from the truck on 2 (`speeding_forklift_06`, `vest_group_cross_10`).
- Smoke G replay: the truck footpoint is the bottom of the SAM mask in each recorded frame (12 fps, 60 frames), through the same homography, against the structure's base segment on the floor.
  No new SAM call: the replay reads smoke G's recorded tracks.
- Informational readings, set before the run: whether `collision_racking_22` and `bump_upright_cctv_25` still read a strip contact.
  A strip that never reads contact would pass mark 4 for the wrong reason, and these two show it.

## Result

| # | Mark | Result |
|---|---|---|
| 1 | `speeding_forklift_06` highest peak speed | pass: 3.53 m/s, next is `collision_racking_22` at 1.62 |
| 2 | `speeding_forklift_06` at or above 2.2 m/s | pass: 3.53 |
| 3 | five compliant clips under 2.2 m/s | pass: 1.21, 0.61, 0.47, 0.36, 0.31 (`two_forklifts_vests_09`, `spotter_ahead_01`, `loading_dock_spotter_08`, `reversing_spotter_05`, `vest_group_cross_10`) |
| 4 | no compliant clip has a strip contact | pass: 0 of 5, but see below |
| 5 | two runs byte-identical | pass: all three output files have the same SHA-256 on both runs |

Peak floor speed on all 16 clips, highest first.
`speeding_forklift_06` goes from 2.16 to 3.53 m/s, so it speeds up across the clip.

| Clip | Peak m/s | Truck samples | Footpoints outside the marked quad | Samples with an estimated off-frame rear |
|---|---|---|---|---|
| `speeding_forklift_06` | 3.53 | 3 | 1 | none |
| `collision_racking_22` | 1.62 | 6 | 6 | 0, 3, 4 |
| `no_spotter_04` | 1.37 | 6 | 3 | 0, 1 |
| `bump_upright_cctv_25` | 1.27 | 6 | 6 | 0, 1, 2 |
| `two_forklifts_vests_09` | 1.21 | 6 | 6 | 0, 1, 2, 3 |
| `blind_corner_no_vest_07` | 1.05 | 6 | 4 | 0, 1, 2 |
| `reversing_no_spotter_14` | 0.78 | 6 | 0 | none |
| `near_miss_person_stops_24` | 0.78 | 6 | 5 | none |
| `bump_guard_cctv_28` | 0.73 | 6 | 6 | all |
| `no_vest_pedestrian_03` | 0.71 | 6 | 3 | 0, 1 |
| `no_vest_group_near_11` | 0.71 | 6 | 6 | 0 to 3 |
| `spotter_ahead_01` | 0.61 | 6 | 1 | none |
| `loading_dock_spotter_08` | 0.47 | 6 | 6 | 0 to 4 |
| `reversing_spotter_05` | 0.36 | 6 | 1 | none |
| `vest_group_cross_10` | 0.31 | 6 | 6 | 0 to 3 |
| `scrape_rack_cctv_26` | 0.14 | 6 | 5 | all |

Smoke G replay, strip within 0.30 m of the structure base for 3 frames in a row:

| Clip | Verdict | Closest floor distance to a strip |
|---|---|---|
| `collision_racking_22` (collision, G read contact) | none | 1.14 m |
| `bump_upright_cctv_25` (collision, G read touched) | none | 1.86 m |
| `scrape_rack_cctv_26`, `near_miss_person_stops_24`, `bump_guard_cctv_28` | none | 1.24 m, 1.74 m, 2.10 m |
| the five compliant clips | none | 1.36 m to 4.77 m |

## What it shows

- The five compliant clips stop reading "touched", but so does every other clip.
  `collision_racking_22` asserted contact with a consequence in smoke G, and here its truck never gets nearer than 1.14 m to the rack strip.
  A strip that never fires cannot separate a collision from a compliant pass, so mark 4 passing proves nothing about the strip.
- The footpoint is the bottom of the truck mask, which sits at the rear of the truck, nearest the camera.
  The contact in a collision is at the fork tip and mast, at the front and up in the air, so the rear footpoint stays about a truck length from the rack.
  Piece 13 needs a fork-tip footpoint or an approach-speed test, and this replay has neither.
- The speed ranking works in order: `speeding_forklift_06` leads by more than a factor of two.
  That lead rests on two intervals, because the truck is in frame at only three samples, and the fastest interval ends on a sliver of rear at the top edge.

## What it does not prove

- Metric speed: the scale is a pre-set 3.0 m truck length and a 1.15 m width, with a pallet on one clip only, so the numbers hold as an order only.
  A pass within 10% needs telematics on real footage.
- A held-out floor point: piece 5 asks for a fifth point and a reprojection error, and none was measured.
  Footpoints fall outside the marked quad on 15 of 16 clips (65 of 93 samples), so most speeds are extrapolated beyond the points that fixed the plane.
- Hand marks of high quality: the marking passes report low confidence on the floor rectangles in all four batches.
  Boxes are good to about 10 px, which is a few tenths of a metre far from the camera, and hidden fork tips and rear edges were estimated.
- 1 Hz sampling: a truck that crosses the frame in two seconds, as `speeding_forklift_06` does, gets one or two intervals, and the one-second smoothing of piece 6 could not run.
- A structure strip that works: the replay never reads contact.
- Real footage, moving cameras, or trucks seen from the driver's seat.

## Needs

- A footpoint that reaches the structure: the fork tip or the front of the truck mask projected to the floor, tested on `collision_racking_22` and `bump_upright_cctv_25` first, with a mark set before the run (both must read strip contact, the five compliant clips must not).
- Samples at 4 fps or more for the speed series, from tracked boxes rather than hand boxes, so the smoothing and the stop test can run.
- A fifth, held-out floor point per camera, and pallets or measured floor marks as the scale on at least a few clips.

## Files

The homography and smoke scripts, the hand marks and both runs' outputs are kept with this experiment's private record.
