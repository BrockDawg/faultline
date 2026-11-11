# Smoke test D: the forklift scan locator (27 Oct 2026)

Scripts only, no model, no paid call, $0.
The design it tests is [the forklift scan route](../../docs/forklift-scan-route.md); this log keeps the smoke that ran while that design was written.

## Question

Can a script walk a long warehouse clip with no report and return a short list of active windows, the same way every run?

## Method

- `scripts/build_shift.py` joins 28 single-view synthetic clips into one 421 s "shift" under an opaque name, with a 10 s noisy idle gap before each clip; `manifest.json` is the answer key (idle and active spans).
- `scripts/locate.py` sees only the video: ffmpeg `scdet` for cuts, a static-camera check, motion candidates with hysteresis and a minimum duration.
- `scripts/score.py` scores the windows against the manifest; `run1.json` and `run2.json` are two runs.
- `scripts/diag.py` and `scripts/pan.py` check camera motion on each source clip.
- The shift video and the segments are rebuilt by `build_shift.py` from the synthetic clips, which stay local and out of git.
- The scripts, the manifest and the two run files are kept with this experiment's private record.

## Result

| Measure | Result |
|---|---|
| Active spans found | 28 of 28 |
| Windows raised in idle gaps | 0 |
| Same output on two runs | yes, byte-identical |
| Cuts found by ffmpeg `scdet` | 27 of 27 (the hand-written cut rule found 23) |

## What it does not prove

- Precision against breaches: compliant clips raise windows too, because the locator finds activity, not rule breaks.
  Breaches come from the colour, spotter and candidate pieces, none built yet.
- Only 16 of the 28 synthetic clips are fixed-camera; 12 have a moving camera (`collision_pallet_stack_23` is a driver view, `spotters_front_and_back_02` tracks the truck, `_02_alt` pans 15 px).
  The moving-camera thresholds were set after looking at those clips, so they need a check on clips they were not tuned on.
- Metric thresholds cannot be validated on AI-made clips; ordinal checks only.

## Needs

- torch (CPU build) and transformers for the person detector (Meta's DETR ResNet-50, pinned weights); neither is installed.
- Real footage for horn audio, fleet numbers and night vest reads.
