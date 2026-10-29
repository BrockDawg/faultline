# Round 4: the footpoint clearance fix (28 Oct 2026)

The cheapest next step from [the Blender twin](../2026-10-28-round-4-blender-twin/LOG.md).
It re-scores the twin's recorded truth boxes and SAM boxes, with no new render and no paid call, $0.

## Question

The twin found that the truck box's bottom edge is the counterweight's underside, 0.12 m above the floor.
Treating it as floor read every speed 3.9% high and put the inferred fork tip about 0.4 m too far forward, so the front-point contact rule failed on perfect inputs.
If the box-bottom footpoint is projected onto the plane at the counterweight's clearance height instead of the floor, does that bias go, and does the contact rule then pass?

## Pre-registration (committed before the first run)

### Method

- Inputs, unchanged from the twin: the truth boxes, the SAM box-prompt boxes (12 fps) and the truth camera.
- The footpoint is the bottom-centre of the truck box, as before.
- The change: the image-to-floor map for the footpoint is the homography of the plane z = h, built from the camera matrix, not the floor's.
  The point found on that plane sits straight above its floor point, so its x and y are the floor position.
- h = 0.12 m, the counterweight clearance in the scene (a spec-sheet number for a real truck).
- Speed, the front-point contact rule (3.0 m ahead along the travel direction, 0.15 m strip, 3 frames in a row) and the rear rule are the twin's code, unchanged.
- Arms: A' (truth boxes) and C' (SAM boxes).
  The two hand-homography arms have no camera matrix, so this fix cannot reach them without a camera height; they are not run.

### Pass marks

| # | Mark |
|---|---|
| F1 | A' peak speed within 1% of truth on 8 of 8 clips (6 ladder, 2 reversing) |
| F2 | A' front-point rule fires within 3 frames of the truth contact frame (84) and never on the near pass |
| F3 | C' front-point rule fires within 4 frames of 84 (SAM runs at 12 fps) and never on the near pass |
| F4 | C' peak speed within 2% of truth on 8 of 8 clips |

Reported, never a mark: A' at h = 0.10 and 0.14 m (a 2 cm spec error), the corrected footpoint's floor distance from the truth rear-centre, and the rear rule.

## Result

All four marks pass.
Two runs gave byte-identical output.
Check: the z = 0 map built from the camera matrix matches the truth floor homography.

| # | Result |
|---|---|
| F1 | pass: A' speed +0.02% on all 8 clips (before the fix: +3.9%) |
| F2 | pass: A' fires at frame 82 against truth 84 (before: 75), silent on the near pass (closest 0.34 m against truth 0.30) |
| F3 | pass: C' fires at 82, silent on the near pass (closest 0.37 m) |
| F4 | pass: C' speed within 1.9% on all 8 clips (worst +1.86%) |

The rear rule still never fires on either clip.

### A 2 cm error in the clearance (reported)

| h | A' speed error | Contact frame | Near pass closest |
|---|---|---|---|
| 0.10 m | +0.67% | 81 | 0.27 m, silent |
| 0.12 m | +0.02% | 82 | 0.34 m, silent |
| 0.14 m | -0.63% | 84 | 0.41 m, silent |

A 2 cm spec error moves speed by about 0.65% and the contact frame by 1 to 2 frames.
The near pass stays silent at all three heights, but at h = 0.10 its margin is only 0.12 m over the 0.15 m strip.

### Footpoint against the truth rear-centre (reported)

- The median floor distance falls from 0.28 m to 0.04 m (n = 48 sampled frames).
- The maximum grows with range: 0.11 m at 11.5 m, 0.26 m at 16 m, 0.45 m at 21 m.
  Every residual over 0.10 m is beyond 11 m from the camera.
  The cause is not checked; a likely one is that at a shallow view angle the box's lowest pixel stops being the counterweight's rear edge.
- Peak speed hides this, because it keeps only the largest step, so a distance or contact read beyond about 11 m needs this checked first.

## What it does not prove

- h and the camera matrix come from the twin, so they are exact.
  A real site needs the truck's spec-sheet clearance and a calibrated camera; hand floor marks give neither.
- Contact is one clip and the near pass is one clip.

## Needs

- The hand-homography arms need a camera height to use this fix: solve the camera from the floor homography plus one known height (the mast or the overhead guard).
- Check the far-range residual on the masks before any reading beyond 11 m ships.
