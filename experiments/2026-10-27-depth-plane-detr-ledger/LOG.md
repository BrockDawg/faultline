# The floor plane from depth, and a GPU detection ledger (27 Oct 2026)

Both parts ran on one Modal L40S.
No Meta, Baseten or SAM call was made: $0 through the metering proxy.
Every mark and threshold was written down before any model ran on any frame, and none changed after.

## Question

B1: can a GPU detector give every clip a replayable per-frame ledger of people and trucks, the same bytes every run?
B3: can Depth Anything V2 Small give the floor plane and a metric scale from one frame, close enough to replace the four hand-marked floor points?

## Method

- Clips: the 47 synthetic clips, 121 frames each at 1280 x 720, 24 fps, 5,687 frames.
  "Fixed camera" means the 16 fixed-camera clips of [smoke test H](../2026-10-27-smoke-h-detector-ruling/LOG.md).
  The synthetic clips stay out of git.
- Runtime: torch 2.5.1 (CUDA 12.4), transformers 4.46.3, PyAV 13.1.0, fp32, TF32 off, `torch.use_deterministic_algorithms(True)`, seeds 0.
  The deterministic flag raised nothing on either model.
- B1: `PekingU/rtdetr_r50vd` (revision `df939e66…`, weights SHA-256 `5263d552…`), one frame at a time, `person` and `truck` kept, score 0.5, boxes in whole pixels, one JSON a clip keyed by the SHA-256 of the decoded RGB frame.
  Every other COCO class seen at 0.5 is only tallied.
- B3: `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf` (revision `8078d68a…`, weights SHA-256 `e990eb82…`) on the per-pixel median of each fixed-camera clip's 121 frames.
  Assumed intrinsics: 60 degrees horizontal field of view, principal point at the centre.
- Plane fit (numpy only, local): candidate floor pixels are rows 360 and below, outside every ledger person or truck box in any frame (grown by 8 px).
  RANSAC on the candidates, accepted if the inliers are at least 30% of the candidates and the normal is within 50 degrees of the camera's vertical axis.
  Then smoke J's hand marks and smoke H's person footpoints are cast onto the plane and scored with smoke J's own distance rule.
- Each model ran twice, each run in a fresh container, after one one-clip check run.

## Result: B1, the detection ledger

| Mark (fixed first) | Result |
|---|---|
| 5,687 frames, 121 for each of 47 clips | Met |
| Two fresh-container runs byte-identical | Met: all 47 clips identical, and the ledger SHA-256 over the 47 equal in both runs |
| Person count right at frame 60 on at least 15 of 16, driver rule | Met: 15 of 16 |
| A truck box in all 121 frames on at least 12 of the 15 clips with a hand-marked truck at frame 60 | **Not met: 4 of 15** (`near_miss_person_stops_24`, `scrape_rack_cctv_26`, `loading_dock_spotter_08`, `no_vest_pedestrian_03`) |
| A truck in every frame of every fixed-camera clip | Not met (reported only) |

- The person miss is `vest_group_cross_10`: four people close together, RT-DETR gave three, the same miss DETR made in smoke H.
- Frames with a `truck` box, of 121: 45 in `spotter_ahead_01`, 60 in `blind_corner_no_vest_07`, 71 in `collision_racking_22`, 73 in `bump_guard_cctv_28`, 83 in `no_spotter_04`, 87 in `two_forklifts_vests_09`, and 113 to 121 in the other fixed-camera clips.
  The truck is lost in the middle of a clip more often than not, so a tracker on these boxes needs gap handling, or another truck source.
- Other classes at 0.5 over all 47 clips: `train` 539, `bench` 779, `chair` 333, `skis` 378, `skateboard` 270, `refrigerator` 149, `suitcase` 134, `diningtable` 121, `car` 78, `bus` 13 and a few more.
  Whether the `train` boxes are the forklift body was not checked.
- Determinism note: the ledger files carry a timing field, dropped before comparing, because it is not ledger content.
  Three new clips were added to the synthetic folder between the two runs, so run 2 saw 50 clips; those three are not compared.

## Result: B3, the floor plane from depth

| Mark (fixed first) | Result |
|---|---|
| A plane accepted on at least 14 of 16 cameras | **Not met: 10 of 16** |
| Two fresh-container runs give identical rounded planes | Met: 16 of 16 planes identical, all 16 depth maps byte-identical |
| `near_miss_person_stops_24` reads the smallest person-to-truck distance | Met: 0.237 m (smoke J: 0.186 m) |
| Spearman rank correlation with smoke J's per-clip minimum at least 0.8 | **Not met: 0.6, over 6 clips** (two J clips have no accepted plane) |
| Hand-marked truck body 1.80 to 3.00 m long on at least 12 of 15 clips with a reference | **Not met: 1 of 10** that had a plane |
| `speeding_forklift_06` reads the fastest truck | **Not met**: it has no accepted plane |

- Six planes were refused.
  Four had no candidate pixels left (`bump_guard_cctv_28`, `no_vest_group_near_11`, `no_vest_pedestrian_03`, `speeding_forklift_06`), because the all-frames box rule covers every floor pixel at rows 360 and below.
  Two had a normal more than 50 degrees from vertical (`collision_racking_22` 54.8, `no_spotter_04` 79.9).
- The accepted planes look plausible: the normal sits 28 to 48 degrees from the camera's vertical axis and the camera height reads 1.8 to 3.5 m.
  Four of them report 100% inliers from only 540 to 4,725 candidates, so those fits rest on small floor patches.

Person-to-truck distance in metres, the depth plane against smoke J's floor homography:

| Clip | Depth plane | Smoke J |
|---|---|---|
| `near_miss_person_stops_24` | 0.24 | 0.19 |
| `loading_dock_spotter_08` | 0.29 | 0.63 |
| `spotter_ahead_01` | 0.58 | 2.37 |
| `vest_group_cross_10` | 0.92 | 0.90 |
| `two_forklifts_vests_09` | 1.17 | 1.64 |
| `reversing_spotter_05` | 1.22 | 1.14 |

- The median ratio to J is 0.72 where J reads above 0.3 m.
- Hand-marked truck body length on the depth plane, for the 10 accepted clips: 0.94, 1.06, 1.48, 1.60, 1.62, 1.77, 1.79, 2.59, 3.25 and 7.10 m (the last is `reversing_no_spotter_14`, a plane far from the truck).
  Two of ten sit in the 2.5 to 3.5 m counterbalance range; widths read 0.36 to 1.54 m against 1.2 m.
- Truck footpoint speed, ledger boxes on the plane, 10 clips read: `spotter_ahead_01` 0.67 m/s, `reversing_no_spotter_14` 0.59, `reversing_spotter_05` 0.37, `blind_corner_no_vest_07` 0.36, `two_forklifts_vests_09` 0.33, `near_miss_person_stops_24` 0.31, the rest 0.05 or less.
  The clip labelled fast is not read.
- Field of view sensitivity, reported only: at 50 degrees 10 planes, Spearman 0.6, 1 of 10 in band; at 70 degrees 9 planes, Spearman 0.4, 3 of 9 in band.

### Exploratory, not a mark: floor mask from frame 60's boxes only

Run after the results above, to ask whether the mask rule alone caused the misses.
It gates nothing and changes no verdict above.

- 14 of 16 planes accepted (`no_vest_group_near_11` still has no candidates, `no_spotter_04` still fails the angle test).
- `near_miss_person_stops_24` is no longer the smallest: `no_vest_pedestrian_03`, which has a plane now, reads 0.17 m.
- Spearman 0.71 over 7 clips, truck body length in band on 1 of 13, median ratio to J 0.59.
  `speeding_forklift_06` has a plane and is still not the fastest (`spotter_ahead_01` at 0.59 m/s is).
- So the mask rule cost most of the missing planes, but the scale and rank marks fail with it fixed.

## Cost

- Modal dashboard, read at 20:10 on 27 Oct: this experiment's app billed $0.67 across eight job rows between 17:00 and 19:00.
  That includes two failed launches and container start-up.
- GPU compute read from the runs: 869 s, 14.5 minutes (ledger 324 s and 358 s, depth 92 s and 86 s, one-clip check 9 s), against a 15-minute mark: met.
- Wall time of the five runs was 1,130 s, which at $1.95 an hour estimated $0.61 against a $0.60 mark; the dashboard figure is 6 cents above that estimate.
- Two earlier launches failed before any clip ran, one on a path computed in the container and one on a version object that could not travel back.
- Paid model calls: none.

## What it does not prove

- Every clip is AI-made, so a pass would have been an upper bound; the failures are not.
- Smoke J's metres rest on an assumed 1.2 m by 2.4 m truck, so agreement with J is agreement with an assumption, not with the world.
- The intrinsics are assumed; the clips carry none, and the scale mark moves with the choice.
- "Outside every detector box" stands in for "floor", because no detector finds floor.
- RT-DETR's `truck` class is the COCO class, not a forklift class, so the 4 of 15 may say more about the class than about the model.
- The ledger shows determinism on one GPU type, one container image and one decode library; another GPU would need its own diff.
- Depth Anything V2 Metric Small's licence line was not on its model card, and the Apache 2.0 reading comes from the official README, not re-read here.
- Smoke I's marks were not compared here.

## Needs

- Compare smoke I's hand points and its fastest clip with these planes.
- If B3 is tried again: a mask from the median frame's own detector boxes, an intrinsics guess per camera from the one hand-marked truck, and the scale taken from the hand reference instead of the metric head.
  That is a new experiment with new marks, not a rerun.
- B1 as it stands is usable for people, and for smoke K's tracker, as replayable boxes; for trucks it needs gap handling or the SAM boxes.
- Whether the `train`, `car` or `bus` boxes are forklifts needs one look at a frame sheet.
- The four hand points stay a one-off setup step per camera until a depth route passes a mark.

## Files

The GPU and analysis scripts, the marks file, both ledgers, the depth maps and the results are kept with this experiment's private record.
