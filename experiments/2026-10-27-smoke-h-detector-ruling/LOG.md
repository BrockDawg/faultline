# Smoke test H: person detector and one ruling (27 Oct 2026)

Part 1 is free and local.
Part 2 is paid: six Spark Open calls through the metering proxy, on Brock's go.
The design it tests is pieces 3 and 12 of [the forklift scan route](../../docs/forklift-scan-route.md).

## Part 1: DETR ResNet-50 on the 16 fixed-camera clips

- Model `facebook/detr-resnet-50`, revision `1d5f47bd3bdd2c4bbfa585418ffe6da5028b4c0b`, weights file SHA-256 `830f5e2e…20ad81` checked in code before every run.
- CPU, one thread, `torch.use_deterministic_algorithms(True)`, "person" class only, score 0.9 (fixed before the run), boxes in whole pixels, middle frame (frame 60 of 121) of each clip.
- `timm` is not installed and would pull `torchvision`, so `scripts/detect.py` maps the checkpoint's timm ResNet keys onto transformers' own ResNet and loads with no missing or unexpected keys.
- Hand counts (`hand_counts.json`) were written from the frames before the detector ran.
  The driver rule is piece 4's, simplified: a person whose box centre lies inside a truck box is the operator.
  The truck boxes are hand-drawn stand-ins for the SAM truck boxes.
- The scripts, the hand counts and the run files are kept with this experiment's private record, and the synthetic clips stay out of git.

| Measure | Result | Pass mark |
|---|---|---|
| Person count right, driver rule applied | 15 of 16 | 14 of 16 |
| Person count right, no driver rule | 10 of 16 | none |
| Operators dropped by the rule | 5 (08, 03, 11, 14, 24) | none |
| Two runs | byte-identical (second run on freshly decoded frames) | zero changed bytes |

- The one miss is `vest_group_cross_10`: four people walking close together, DETR gave three.
- Not tested: "every truck found in every clip", which needs SAM.

## Part 2: one ruling, six windows

- Windows: `spotter_ahead_01`, `loading_dock_spotter_08`, `vest_group_cross_10` (compliant) and `no_vest_pedestrian_03`, `reversing_no_spotter_14`, `bump_upright_cctv_25` (one breach each).
- Opaque case ids (`case-` and 8 hex of a seeded hash), shuffled order, 5 frames per window at 960 px with metadata stripped, the four `forklift-site-rules` rules, a fact sheet from part 1 with a fixed limitation sentence.
- `meta-models/muse-spark-open-1026`, temperature 0, `max_tokens` 6000.
- Code post-check: rule id, verdict and frame numbers must sit in their enums, and every rule must get one finding.

| Case | Window | Key | Result |
|---|---|---|---|
| 44bbd02e | `no_vest_pedestrian_03` | hi-vis breach | hi-vis breach found; also false breaches on spotter and separation |
| 233b688d | `vest_group_cross_10` | none | false separation breach |
| 426af666 | `reversing_no_spotter_14` | spotter breach | no ruling: `finish: length`, 5,997 of 6,000 tokens spent reasoning |
| 94e44dac | `bump_upright_cctv_25` | structure breach | no ruling: `finish: length`, 5,997 of 6,000 tokens spent reasoning |
| f364a114 | `spotter_ahead_01` | none | clean (separation `cannot_judge`) |
| bfe38c73 | `loading_dock_spotter_08` | none | false separation breach |

- Pass mark (from piece 12, scaled down): no compliant clip ruled a breach, and the labelled clips ruled under the right rule.
  **Not met**: 2 of 3 compliant windows got a false breach, and 1 of 3 labelled windows was ruled under the right rule (2 returned nothing).
- Cost: the six Spark Open rows in the ledger sum to $0.1413 (expected about $0.10, ceiling $0.20).
  The ledger's token total moved by $0.2373 over the run because other runs spent through the same proxy at the same time.

## What it shows

- Every false breach is on `pedestrian_separation`, whose pack text still holds the placeholder "[3] metres".
  The model asserted "about 1 m" with no scale in the frames, so a distance rule needs the measured floor distance from piece 5, never an eyeballed one.
- A rule judged without its measurement gives a confident wrong breach, which is worse than a wrong pass.
  Piece 12's code check (keep the measured candidate and the model's verdict side by side) is what should catch it; it is not built.
- Spark Open reasons for about 3,000 to 6,000 tokens on a four-rule, five-frame call, and 2 of 6 calls hit 6,000.
  A window call needs a ceiling of 10,000 or more, or one call per rule instead of one call for all four.
- Reasoning aside, the model read vests and the rear path right on the clips where it finished.

## Needs before a rerun

- Fill or drop the pack placeholders, and give the model a measured distance or leave the rule out of the ruling.
- Raise `max_tokens` (or split per rule), then rerun the two truncated windows.
- Frames and the detector weights stay out of git; the case-to-clip map is the answer key, kept with this experiment's private record.
