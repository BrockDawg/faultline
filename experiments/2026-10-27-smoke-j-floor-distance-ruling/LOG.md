# Smoke test J: floor distance and the smoke H rerun (27 Oct 2026)

Part 1 is free and local.
Part 2 is paid: six Spark Open calls through the metering proxy, once I approved them.
The design it tests is pieces 5, 8 and 12 of [the forklift scan route](../../docs/forklift-scan-route.md).
Pass marks were written down first, before any distance existed.

## Part 1: person-to-truck distance in floor metres, 16 fixed-camera clips

- Smoke I's marks were not available when this ran, so these are this test's own marks.
- Floor points: the four floor corners of one reference truck per camera, marked by hand on frame 60 (1280 x 720) from a 100 px grid, mapped to a 1.2 m by 2.4 m rectangle.
  Homography by direct linear transform in numpy, no OpenCV.
  The marks were drawn back over the frames and checked by eye before any distance was computed; two were wrong and fixed then (`no_vest_group_near_11`, `scrape_rack_cctv_26`).
- The scale is assumed, not measured: the synthetic clips have no true scale, so every metre is "a metre if the truck is 1.2 m wide".
- Person footpoint: bottom centre of the DETR box from [smoke test H](../2026-10-27-smoke-h-detector-ruling/LOG.md), with operators dropped by the hand truck boxes as in H.
- Truck footprint: the body quad plus a quad for the forks, mast and load where they show, plus any second truck; distance is footpoint to the nearest edge, 0 if inside.
- Frame 60 only, so these are the distances at one moment, not the minimum approach.
- `speeding_forklift_06` has no truck in frame 60, so it has no scale reference and is skipped.
- The synthetic clips stay out of git.

| Clip | Label | People on foot | Distance to truck (m) |
|---|---|---|---|
| `near_miss_person_stops_24` | near miss | 1 | **0.19** |
| `no_vest_pedestrian_03` | breach | 1 | 0.42 |
| `loading_dock_spotter_08` | spotter, compliant | 1 | 0.63 |
| `vest_group_cross_10` | compliant | 3 | 0.90, 0.95, 1.08 |
| `reversing_spotter_05` | spotter, compliant | 1 | 1.14 |
| `two_forklifts_vests_09` | compliant | 1 | 1.64 |
| `spotter_ahead_01` | spotter, compliant | 2 | 2.37, 2.98 |
| `no_vest_group_near_11` | breach | 2 | 3.62, 3.93 |
| the other seven | | 0 | none (no person on foot at frame 60) |

| Mark (fixed first) | Result |
|---|---|
| `near_miss_person_stops_24` reads the smallest distance | Met: 0.19 m, next is 0.42 m, and below every compliant clip (smallest 0.63 m) |
| Spotter clips at or above 0.5 m | Met: 2.37, 1.14 and 0.63 m |
| Two runs byte-identical | Met: both output files hash `f4e61c3d…514466` |

- Scale cross-check, reported and not gated: the distance between the aisle's two rack feet on one row, assumed 3.0 m plus or minus 0.6.
  Three of six land inside (2.93, 3.38, 3.50) and three do not (2.19, 3.89, 3.95).
  So the metres are good to roughly plus or minus 30%, which is enough to order clips and not enough to hold a 3 m line to the decimetre.
  Piece 5's 2% rule on a fifth held-out point is not met by hand marks on AI-made clips; it needs one real camera with measured points.
- The near miss reads 0.19 m only because the forks are in the footprint: the person stands at the tine tips, about 1.8 m from the body alone.

### What part 1 shows

- Every person on foot in the compliant clips reads under the 3 m site distance, the farthest (2.98 m in `spotter_ahead_01`) by 0.02 m.
  A distance rule with no truck motion and no spotter or crossing exemption will see "within 3 m" in all three compliant windows of part 2.
  Piece 12's fact sheet therefore needs the truck's speed (piece 6) next to the distance, or the rule text needs its moving clause measured, not left to the model.

## Part 2: the smoke H rerun, six windows

- Windows, frames and answer key as in smoke H, new seeded opaque case ids, `meta-models/muse-spark-open-1026`, temperature 0, `max_tokens` 12000.
- Changes from H: the pack's "[3] metres" placeholder reads "3 metres" from the site file; each person on foot carries "feet X.X m from the truck" from part 1; one added sentence says the distances are approximate and say nothing about motion.
  The spotter rule's own placeholder is left as in H.

| Case | Window | Key | Result |
|---|---|---|---|
| 50577382 | `loading_dock_spotter_08` | none | false separation breach (reads 0.6 m, "the forklift is moving forward into the trailer") |
| 89b74312 | `no_vest_pedestrian_03` | hi-vis breach | hi-vis breach found; also a separation breach (0.4 m) |
| d450b606 | `vest_group_cross_10` | none | false separation breach (about 1 m) |
| d353294f | `spotter_ahead_01` | none | false separation breach (2.4 m) |
| 97fdb6a7 | `bump_upright_cctv_25` | structure breach | structure breach found, nothing else |
| dc2688f7 | `reversing_no_spotter_14` | spotter breach | no breach on any rule: "forklift travels forks-first away from the camera" |

| Pass mark | Result |
|---|---|
| No compliant window ruled a breach | **Not met**: 0 of 3 clean; all three got a separation breach |
| 3 of 3 labelled windows ruled under the right rule | **Not met**: the right rule was found in 2 of 3 (03 and 25) and missed on 14; only 25 was ruled with nothing extra, so 1 of 3 by the strict reading |

- All 6 calls finished with `stop` (3,149 to 4,322 completion tokens against the 12,000 ceiling), so the truncation seen in H is gone.
- Cost: $0.1279 on the proxy ledger (24,362 tokens in, 22,929 out), against about $0.15 expected and a $0.352 ceiling.

## What it shows

- The placeholder fix worked as a fix and failed as a test: with a measured distance the model no longer invents one, and it reports the measured one correctly.
  Every compliant window is then ruled a breach, because each really has a person under 3 m and the sheet carries no truck speed, so the model decides "the truck is moving" from the frames.
  The rule is a moving-truck rule; the measurement it needs is truck speed against distance (piece 6 with piece 8), and the pass mark cannot be met without it.
- A dock guide at 0.6 m and a vested crossing at 1 m are compliant by label, so a flat 3 m line also needs an exemption the pack does not state (a vested spotter at a dock, a stopped truck at a crossing).
  Both are site-file or rule-text decisions, not model skill.
- `reversing_no_spotter_14` is missed on a direction read: the model says the truck travels forks-first away from the camera, while the clip's truck faces the camera with its forks toward it.
  That is piece 9's job (travel direction against the fork end, by script), not something to hand the model.
- The hi-vis read and the structure contact read were right on the clips where they were due, as in H.

## Files

The marks, the site value, the hand floor marks, the part 1 result, the floor, overlay and rule scripts and the six case replies are kept with this experiment's private record.
Frames and overlays stay out of git, and the case-to-clip map is the answer key.
