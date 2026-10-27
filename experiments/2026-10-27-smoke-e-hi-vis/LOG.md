# Smoke test E: the hi-vis colour rule (27 Oct 2026)

Scripts only, no model, no paid call, $0.
The design it tests is piece 7 of [the forklift scan route](../../docs/forklift-scan-route.md).

## Question

Can a script read a person's vest from colour alone, in three states (vested, unvested, unknown), without ever calling a vested person unvested?

## Method

- The first run was the 16 fixed-camera synthetic clips (set `fixed_16`).
  A second run added the other 19 single-view clips (set `rest`), all moving-camera; see the extension below.
- `boxes.json` is the hand-drawn answer key: one frame per clip (frame 60 of 121; frame 105 for `blind_corner_no_vest_07`, where the person has not entered at frame 60), a box per person, a role (pedestrian or driver) and what the person wears.
  The key holds 13 pedestrians (9 vested, 4 unvested) and 5 drivers.
- `scripts/hivis.py` sees the video and the boxes only.
  The mask is what differs from the clip's own temporal median (the empty scene of a fixed camera) by more than 45 in RGB distance, inside the box.
  The torso band is 20 to 60% of the box height, tested in HSV for yellow-green (hue 55 to 85) and orange-red (hue 8 to 28).
  Vested is a vest-colour share of at least 0.15 of the mask pixels in the band, unvested is below 0.05, anything between is unknown.
  Unknown is forced for a box under 40 px tall, a box cut by the frame edge, or fewer than 60 mask pixels in the band.
- All thresholds were written before the first run and were not changed after it.
- The same script also reads each box with no mask, to show what the mask adds.
- `run1.json` and `run2.json` are two runs.
  The script needs only numpy, Pillow (for `--debug` panels) and ffmpeg.
- The script, the answer key and the two run files are kept with this experiment's private record, and the synthetic clips stay out of git.

## Result

| Measure | Pass mark | Mask rule | Box only |
|---|---|---|---|
| Vested people read unvested | 0 | **0 of 9** | 0 of 9 |
| Unvested people found | at least 3 of 4 | **4 of 4** | 4 of 4 |
| Vested people read vested | none set | 6 of 9 | 3 of 9 |
| Vested people read unknown | none set | 3 of 9 | 6 of 9 |
| Unvested people read vested | none set | 0 | 0 |
| Same output on two runs | yes | byte-identical | |

The three vested people the mask rule left at unknown:

- `reversing_spotter_05`: cut by the bottom frame edge, so unknown by rule (vest share was 0.322).
- `spotter_ahead_01` p1: stands still, so the median absorbed them and only 324 mask pixels were left, share 0.062.
- `vest_group_cross_10` p2: share 0.134, under the 0.15 line, in a group of three overlapping boxes.

All four unvested people read exactly 0.000.
`blind_corner_no_vest_07`, which the design expected to come out unknown, read unvested: the person is 120 px tall, not tiny by the 40 px rule.

Two drivers would have read unvested if they had been counted (`scrape_rack_cctv_26` at 0.000, `two_forklifts_vests_09` at 0.039), because the cab frame hides the vest.
So the driver rule is not decoration: the driver must be excluded before the colour test.
Here the driver is a hand label, not a measured thing.

## Extension: the other 19 clips, and a category for every clip

The synthetic folder holds 47 files.
35 were read (the 16 above and 19 more), and each carries a view, a camera and a set in `boxes.json`.
12 were not read, for the reasons below.

Views: `cctv_fixed` (high fixed camera, the 16), `side_tracking` (a side view that follows or pans with the truck), `driver_pov_forward` (the forks in view, looking ahead) and `rear_cam` (looking back past the carriage).

A moving camera has no empty-scene median, so there is no person mask.
On those 19 clips the script reads the torso band of the box only, with the same thresholds.
That is the rule the design calls the fallback, so it is the number that matters for them.

| Measure (moving-camera clips, box only) | Result |
|---|---|
| Vested people read unvested | **1 of 11** (`forklift_pov_no_vest_13`) |
| Vested people read vested | 7 of 11 |
| Vested people read unknown | 3 of 11 (`spotters_front_and_back_02` p1 and p2, `forklift_pov_pedestrian_12`) |
| Unvested people found | 3 of 3 (`pov_forward_no_vest_close_17`, `rear_cam_no_vest_behind_20`, `B_rear_novest`) |
| Same output on two runs | byte-identical |

The one miss fails the pass mark on this set: zero vested people read unvested.
`forklift_pov_no_vest_13` is named and labelled "no vest", but frames 30, 60 and 90 show a pale lime vest over a grey top, so the key says vested (`key_note` in `boxes.json`).
The vest sits outside the thresholds: zero band pixels pass, and the median saturation is 0.14 against a floor of 0.45 (distance and blur wash it out).
Widening only the hue (55 to 110) or only the saturation floor (0.25) catches 0.2% and 1.9% of the band; widening both catches 14.6%, still under the 0.15 line.
So no single-number retune fixes it.
(Measured on a hand-picked vest patch of the frame, not on the box the script uses.)
Thresholds were not changed after seeing this.

By view, box only:

| View | Vested read vested / unvested / unknown | Unvested found |
|---|---|---|
| `cctv_fixed` (mask rule) | 6 / 0 / 3 | 4 of 4 |
| `side_tracking` | 2 / 0 / 2 | none in frame |
| `driver_pov_forward` | 2 / 1 / 1 | 1 of 1 |
| `rear_cam` | 3 / 0 / 0 | 2 of 2 |

Every clip, with its category and what the script read (the rule used is the mask on a fixed camera, the box alone on a moving one; a driver is listed but never counted):

| Clip | Set | View | Camera | People in frame (truth) | Rule used | Read |
|---|---|---|---|---|---|---|
| `bump_guard_cctv_28` | fixed_16 | cctv_fixed | fixed | none | mask | nothing to read |
| `bump_upright_cctv_25` | fixed_16 | cctv_fixed | fixed | none | mask | nothing to read |
| `collision_racking_22` | fixed_16 | cctv_fixed | fixed | none | mask | nothing to read |
| `near_miss_person_stops_24` | fixed_16 | cctv_fixed | fixed | p1 pedestrian vested, d1 driver vested | mask | p1 vested, d1 unknown |
| `scrape_rack_cctv_26` | fixed_16 | cctv_fixed | fixed | d1 driver vested | mask | d1 unvested |
| `loading_dock_spotter_08` | fixed_16 | cctv_fixed | fixed | p1 pedestrian vested, d1 driver unvested | mask | p1 vested, d1 unknown |
| `reversing_spotter_05` | fixed_16 | cctv_fixed | fixed | p1 pedestrian vested | mask | p1 unknown |
| `spotter_ahead_01` | fixed_16 | cctv_fixed | fixed | p1 pedestrian vested, p2 pedestrian vested | mask | p1 unknown, p2 vested |
| `two_forklifts_vests_09` | fixed_16 | cctv_fixed | fixed | p1 pedestrian vested, d1 driver vested | mask | p1 vested, d1 unvested |
| `vest_group_cross_10` | fixed_16 | cctv_fixed | fixed | p1 pedestrian vested, p2 pedestrian vested, p3 pedestrian vested | mask | p1 vested, p2 unknown, p3 vested |
| `blind_corner_no_vest_07` | fixed_16 | cctv_fixed | fixed | p1 pedestrian unvested | mask | p1 unvested |
| `no_spotter_04` | fixed_16 | cctv_fixed | fixed | none | mask | nothing to read |
| `no_vest_group_near_11` | fixed_16 | cctv_fixed | fixed | p1 pedestrian unvested, p2 pedestrian unvested | mask | p1 unvested, p2 unvested |
| `no_vest_pedestrian_03` | fixed_16 | cctv_fixed | fixed | p1 pedestrian unvested | mask | p1 unvested |
| `reversing_no_spotter_14` | fixed_16 | cctv_fixed | fixed | d1 driver vested | mask | d1 unknown |
| `speeding_forklift_06` | fixed_16 | cctv_fixed | fixed | none | mask | nothing to read |
| `spotters_front_and_back_02` | rest | side_tracking | moving | p1 pedestrian vested, p2 pedestrian vested, d1 driver unclear | box only | p1 unknown, p2 unknown, d1 unvested |
| `spotters_front_and_back_02_alt` | rest | side_tracking | moving | p1 pedestrian vested, p2 pedestrian vested, d1 driver unclear | box only | p1 vested, p2 vested, d1 unknown |
| `bump_upright_pov_27` | rest | driver_pov_forward | moving | none | box only | nothing to read |
| `collision_pallet_stack_23` | rest | driver_pov_forward | moving | none | box only | nothing to read |
| `forklift_pov_no_vest_13` | rest | driver_pov_forward | moving | p1 pedestrian vested | box only | p1 unvested |
| `forklift_pov_pedestrian_12` | rest | driver_pov_forward | moving | p1 pedestrian vested | box only | p1 unknown |
| `pov_forward_no_vest_close_17` | rest | driver_pov_forward | moving | p1 pedestrian unvested | box only | p1 unvested |
| `pov_forward_normal_15` | rest | driver_pov_forward | moving | none | box only | nothing to read |
| `pov_forward_vested_crossing_16` | rest | driver_pov_forward | moving | p1 pedestrian vested | box only | p1 vested |
| `A_fwd_spotter` | rest | driver_pov_forward | moving | p1 pedestrian vested | box only | p1 vested |
| `B_fwd_clear` | rest | driver_pov_forward | moving | none | box only | nothing to read |
| `C_fwd_clear` | rest | driver_pov_forward | moving | none | box only | nothing to read |
| `rear_cam_clear_19` | rest | rear_cam | moving | none | box only | nothing to read |
| `rear_cam_no_vest_behind_20` | rest | rear_cam | moving | p1 pedestrian unvested | box only | p1 unvested |
| `rear_cam_vested_spotter_18` | rest | rear_cam | moving | p1 pedestrian vested | box only | p1 vested |
| `A_rear_spotter_seedance` | rest | rear_cam | moving | p1 pedestrian vested | box only | p1 vested |
| `A_rear_spotter` | rest | rear_cam | moving | p1 pedestrian vested | box only | p1 vested |
| `B_rear_novest` | rest | rear_cam | moving | p1 pedestrian unvested | box only | p1 unvested |
| `C_rear_clear` | rest | rear_cam | moving | none | box only | nothing to read |

Not read:

- `pairs/A_spotter_pair`, `B_novest_behind_pair`, `C_clear_pair` (1280x360 forward and rear side by side): the same footage as the six source clips `A_fwd_spotter`, `A_rear_spotter`, `B_fwd_clear`, `B_rear_novest`, `C_fwd_clear`, `C_rear_clear`, which were read.
- `superseded/pairs_v1/` (9 files): older takes of the same nine pair files, kept in the synthetic set but not part of the live set.
- Counted once: the 35 above include `model_test/A_rear_spotter_seedance` (Seedance, not Kling).
- People-free rows only say that no person is in the one frame read, not that none appears in the clip.

## What it does not prove

- One frame per clip, so the design's "at least 70% of a person's frames in the zone" rule is not exercised.
- A moving-camera person has only the box read, so yellow trucks, racking and floor lines inside the box can count as vest colour; the side-tracking clips put the yellow truck inside the boxes, and no check of that was made.
- Boxes are drawn by hand.
  A detector's boxes will be looser and will drift between frames.
- 13 pedestrians on AI-made clips, one vest style per site.
  The vested and unvested colours here are far apart (lime and orange against navy, black and grey), so a pass here says the rule is not broken, not that it is calibrated.
- Not exercised: the per-camera white balance (the clips carry no reference patch, so none was applied), grey-cast or sodium lighting, dirty vests, infrared night mode.
- The mask comes from a median background, so it fails on a person who stands still (seen once), and it includes any truck that moves with the person.
  The design's mask is a model's person mask (SAM), which this smoke did not call.
- A driver is excluded by label.
  Nothing here tests the real rule, a person box overlapping a truck's cab.

## Needs

- Real footage with the five conditions above before any threshold means anything.
- A person detector's boxes ([smoke H](../2026-10-27-smoke-h-detector-ruling/LOG.md)) to replace the hand boxes, and a person mask to replace the median.
