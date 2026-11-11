# Smoke test F: reversing direction and spotter rule (27 Oct 2026)

Cost: $0.04 of SAM box prompts (4 calls, each 50 frames at $0.01, by the proxy ledger), once I approved them.
The design it tests is piece 9 of [the forklift scan route](../../docs/forklift-scan-route.md).

## What was run

- Three fixed-camera synthetic clips, which stay out of git: `reversing_spotter_05`, `reversing_no_spotter_14`, `loading_dock_spotter_08`.
- One frame per second (frames 1 to 5), scaled to 960 x 540.
- Truck box, fork-end box (tines or mast) and people boxes drawn by hand into `boxes.json`.
  Vest state and the "spotter required" flag are hand-set stand-ins for piece 7 and the site file.
- `scripts/reversing.py` (stdlib only): heading is the mean unit vector from truck centre to fork-end centre; travel is the fork-end centre's move per second; reversing is travel against the heading by more than 5 px/s; the rear cone is 35 degrees either side of the heading, 2 truck lengths deep, with a vested person's footpoint inside it; the operator (centre inside the truck box) is excluded.
- A candidate is raised only when the truck reverses, a spotter is required and the spotter reads absent.

## Result

| Clip | Expected | Read | Pass |
|---|---|---|---|
| `reversing_spotter_05` | reversing, spotter present | forward (4 of 4 seconds) | no |
| `reversing_no_spotter_14` | reversing, no spotter | reversing (4 of 4), spotter absent, candidate raised | yes |
| `loading_dock_spotter_08` | no candidate | forward (4 of 4), no candidate | yes |

- Two runs wrote byte-identical output (`run1.json`, `run2.json`).
- 2 of 3 clips meet the pass mark.
  Clip 05 does not, and the script is not the cause (see below).

## Why `reversing_spotter_05` reads forward

- In the footage the mast end is at the top of the frame and the truck moves up, toward its mast, for the whole clip.
  That is forward travel.
- The vested person follows the truck from behind, walking the same way.
  The cab also shows no operator.
- So the label "reversing" does not match what the footage shows.
  Either the clip's label is wrong, or the clip was generated and the motion differs from the prompt.
- Check: with time reversed (`mut_reversed.json`, a mutation, not a result) the script reads clip 05 as reversing with the spotter present, and clip 14 as forward.
  So the logic reads direction and the rear cone correctly when the motion flips.

## Caveats

- One-second sampling means "held for at least 1 s" is one interval.
  Real use needs 8 fps tracks.
- Boxes are drawn by hand from the frames.
  A second person should redraw them before the numbers are trusted.
- `reversing_no_spotter_14`: the truck leaves the top of the frame, so the rear is out of view on frames 3 to 5.
  It reads "absent" only because two in-view frames (the minimum, `--min-view 2`) show nobody behind.
  With `--min-view 3` it reads unknown (`sens_minview3.json`) and no candidate is raised.
  The minimum was chosen before the run, but the verdict depends on it.
- On the dock clip the truck is cut off by the bottom edge on every frame, so the heading comes from a clipped box.
  The fork end still sits well above the box centre, so it did not flip.
- The cone depth is in truck lengths because there is no calibration yet.

## Files

`boxes.json` (hand), `sam_boxes.json` (SAM truck and fork, hand people), `scripts/reversing.py`, `scripts/sam_track.py`, `run1.json` and `run2.json` (hand), `sam_run1.json` and `sam_run2.json` (SAM), `sens_minview3.json`, `sam_minview3.json`, `mut_reversed.json`, `sam_mut_reversed.json`, `calls.jsonl` and the raw SAM replies.
The scripts, the run files and the replies are kept with this experiment's private record, and the re-encoded clips stay out of git.

## SAM run (paid, approved by me)

- One SAM 3.1 video call per clip through the metering proxy: two hand-drawn box prompts (truck, fork end) on the first frame, tracked forward at 10 fps.
  Truck and fork boxes at 1 s steps replaced the hand boxes; people are still hand-drawn, and the vest is still read by eye.
- `scripts/sam_track.py` makes the calls and builds `sam_boxes.json`; `calls.jsonl` records each call and the ledger delta.
- Same three readings as the hand boxes: 14 reversing with no spotter (candidate raised), 08 forward (no candidate), 05 forward.
  Two runs byte-identical (`sam_run1.json`, `sam_run2.json`).
  Time reversed (`sam_mut_reversed.json`, a mutation): 05 reads reversing with the spotter present, 14 forward.
- The SAM boxes also settle the 05 question without a human reading: its truck box moves up the frame by about 40 px a second (bottom edge 500, 458, 418, 382, 350), and the mast end is at the top.
- Clip 14 is firmer than on hand boxes: SAM's truck box keeps its rear in view on frame 3, so three in-view frames show nobody behind it and it still reads absent with `--min-view 3` (`sam_minview3.json`).

### Things that went wrong or are weak

- Clip 08, first call: both prompt boxes were the same box (only the carriage is in frame at 0 s), and SAM tracked one object.
  That reply is kept apart and not used.
  The second call starts at 1 s, where the carriage differs from the truck, so clip 08 has three one-second intervals, not four.
- Clip 05: SAM's mast box is a sliver (zero width on the first frame), so the fork-end travel for 05 is small and noisy (12 to 27 px a second along the heading).
  The forward reading rests on the truck box, which moves clearly.
  Piece 9 needs a better fork-end prompt, for example the whole upper mast.
- Clip 08: the truck is cut by the bottom edge on every frame, so its rear is never in view.
- `meta_sam_parser` was not installed for this run, so `sam_track.py` reads the boxes from the reply text with a regex.
  Masks were not read.
- Spend: 3 planned calls plus the one repeat for clip 08, 4 calls, $0.04 by the ledger.

## Open question

I think 05 is labelled "reversing with a spotter" but the footage may not show it.
Both the hand boxes and SAM say the truck moves toward its mast.
The label needs a second pair of eyes before 05 is used as a pass mark.

## Does 05 show a reversing truck? (checked after my question)

- `scripts/flow.py` block-matches the truck's interior between 10 fps frames, with no SAM mask and no hand box in the loop.
  Run on the re-encoded clips: the truck interior moves up the frame in every 0.2 s step, 203 px in total on 05, 251 px on 14 and 236 px on 08 (1280 px frame, camera fixed, racks do not move).
- On 05 the mast is at the top of the frame and the counterweight with the beacon is at the bottom (`crop05_first_and_last_frame.png`, first and last frame).
  The truck travels toward its mast, so it goes forward.
  The vested person has their back to the camera and walks the same way behind it.
- On 14 the tines point down the frame and the truck moves up it, so it reverses.
  That label holds.
- So `reversing_spotter_05` does not show a reversing truck.
  The synthetic set's note for it, "vested person follows a reversing truck", came from frame sheets, and the same notes say direction is "not confirmed from stills".
- Not checked: the other spotter clips in the set (`spotters_front_and_back_02`, `spotter_ahead_01`, the pairs).
  One of them may show a truck that really reverses with a spotter behind it.

## The Seedance clip (`model_test/A_rear_spotter_seedance.mp4`), checked at my prompting

- It is a camera on the truck, looking along the forks (the tines are in the foreground), not a fixed camera.
  Smoke F's pass marks are for one fixed camera, so this clip is outside them.
- Both rack sides drift toward the frame centre: the near upright on the left moves right and the near upright on the right moves left, about 65 px per 0.5 s each (`seedance_left_racks_0_to_1p5s.png`, `seedance_right_racks_0_to_1p5s.png`, frames 0.5 s apart).
- `scripts/zoom.py` fits a radial zoom between frames 0.5 s apart on the side racks only.
  The best zoom is 0.90 on every step (mean 0.897), so the scene shrinks and the camera moves away from what it faces.
  Played backwards it reads 1.11 (mean 1.114), which checks the sign.
- Reading: the truck moves opposite to its fork direction, so it reverses.
  This is the first clip in the set where the footage shows that.
- The vested person is ahead of the forks, walks toward the camera, and the vest grows from about 396 to 530 px over 5 s.
  That is a person in front of a reversing truck, not a spotter in its rear cone.
  Piece 9 would read it as reversing with no spotter.
- Control: the two forward POV clips and the rear-camera clips read about 1.00 and 0.96 to 0.97, so the zoom method showed no motion on them.
  Only the Seedance clip gives a clear signal, and no control with known forward motion was available to confirm the positive side except the time-reversed run.
- Not checked: `spotters_front_and_back_02_alt` (also Seedance, side view, the aisle shifts about 6 px per 0.25 s with no zoom).
