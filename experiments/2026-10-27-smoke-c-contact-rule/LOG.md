# Smoke test C: contact assertion rule behind a shot-cut gate

Pieces 7 and 8 of the deterministic-reads design, a private note not in this repo. Scripts on recorded masks cost $0. The one paid SAM track on report 9 ran on Brock's go: $0.0175 ($0.0025 box image, $0.015 video, 75 frames at 30 fps, 26.5-29.0 s).

## What was built

- `shotcut.py`: the shot-cut gate. Grey-histogram distance between neighbouring frames with the four broadcast overlays blanked, a fixed threshold of 0.10, local maximum. No model.
- `contact_rule.py`: the contact assertion rule. Adjacent 1 px for 3 frames in one shot, a consequence (yaw step over 150 deg/s for 3 frames, centroid speed jump, or gap reopening to 12 px) from the start of the run to 0.5 s after it, optional telemetry check. The evidence frame is the consequence onset.
- `score_w104.py`: runs both on the six W1-04 clips, three ways (raw, gated, gated plus the piece 9 mask floor), writes `results_w104.json`.
- `track_report9.py`: the paid step. `plan` is offline. `boxes` and `track` refuse to run without `--confirm`.
- `test_contact_rule.py`: 11 tests on synthetic rows. Five mutations of the rule (cut margin, adjacent-frame count, consequence window, area floor, first-segment-only) each turn a named test red; the baseline is 11 green.
- The scripts, the masks and the call log stay with the private tooling.

## Result on the W1-04 clips

| Clip | Truth | Raw (no gate) | Gated | Gated plus mask floor |
|---|---|---|---|---|
| report 46 stream, 1136-1146 | pair registered by 1142 | registered, not shown on camera | same | same |
| r_report46 1140.0-1142.0 | pair registered by 1142 | contact at 1140.267 | same | same |
| report 10 stream, 1684-1692 | no pair in the key | **false** (two possible unregistered contacts, one on a cut) | adjacent, not proven | same |
| r_report10 1686.5-1688.6 | no pair in the key | possible unregistered (yaw step 1687.133) | same | same |
| report 10 stream, 1568-1576 | none to score | contact at 1574.3 | same | silent |
| r_report10 1570.0-1573.9 | none to score | contact at 1570.533 | same | same |

The gate earns its place once: on report 10 1684 it removes the assertion born on the 1688.533 cut and the one in the next shot. Four of the four scorable windows pass gated; one fails raw.

## Findings, including the ones against the design

1. **The doc's pass mark "no false assertion on the W1-04 windows" is the wrong test.** Report 46 holds a real contact (01 into 334, key stop at 1142), so the rule should assert there, and does on the rescue clip. The right scoring is per window against the key, as above.
2. **A pixel difference cannot find cuts on a panning broadcast.** Steady shots sat at 6 to 8 against 12 to 17 on cuts. The histogram separates the hard cuts (0.106, 0.135, 0.484 against a median of 0.01 to 0.02).
3. **The gate finds 3 hard cuts and misses the soft ones.** The notes name cuts by eye at 1137.5, 1142 (report 46) and 1569, 1570, 1574 (report 10). I looked at contact sheets: 1137.5 and 1142 are a continuous pan with no cut; 1568.8 and 1569.6 are real changes of shot in similar scenery that the histogram scores at 0.02 to 0.04. A motion-compensated difference did not separate them cleanly either. So the gate is not yet proven for same-scenery cuts, and the by-eye cut times in the notes are not a reliable truth set.
4. **The mask floor (piece 9) catches what the gate misses.** The report 10 1574.3 yaw step is a re-acquisition after a soft cut the histogram scored at 0.02; the area-collapse check removes it.
5. **The SAM prompt identity holds only in the shot that holds the prompt frame.** After a cut the track is a re-acquisition, so the rule asserts only in the first shot. Not in the doc; it is what removes the post-cut reopening on report 10 1684.
6. **Gap reopening is the weakest consequence.** Any pass ends with the gap opening. It is kept because the doc names it, but it fires alone on r_report46 at 1140.267, and that one has no second check.
7. **Telemetry changes the verdict as the doc says.** Silent telemetry turns a visible consequence into "possible unregistered contact". The telemetry second for report 46 is 1142 plus or minus 3 (offset error 2, plus the replay's 1 s sampling), so that clip's pass is weak evidence.
8. **The price in the doc is for a short window.** A 26-29 s track at 30 fps would bill about $0.17. The planned window is 26.5-29.0 s at 30 fps, 75 frames: $0.015 for the video and $0.0025 for the box image, $0.0175 in all. B4's 150 deg/s needs 30 fps.

## Report 9 result (the paid track)

**Pass.** Both ungated and with the mask floor, the rule asserts one contact at **27.733 s** (target 27.7-28.0 s, truth sheet 27.6-27.9 s), because of the yaw step on the black car, and it matches B4's 27.73 s.
The masks are adjacent from 26.5 s (the first frame) to 27.967 s, so a first-adjacent-frame read would have been 1.2 s early; the consequence-onset rule is what lands it.
The telemetry second given was 27.75 (video_offsets.json, contact te 331-332), so the three-part test agrees.
No cut falls in the window, so the gate had nothing to remove here.

Deviation: SAM's box call found only the purple car (plus a 29 x 12 px sliver), so the second car's box was drawn by hand from `first.jpg` (575,337,705,462) into `pick_report9.json`. The track script reads a list as a hand-drawn box.
Which car is #959 and which is #555 was not read: the rule is symmetric in the two cars.
It is not a project dependency.

## Two more clips (Brock's go; $0.038: report 13 $0.0205, report 9 10-12.5 s $0.0175)

| Clip | Truth | Rule says | Verdict |
|---|---|---|---|
| report 9 26.5-29.0 s | contact 27.6-27.9 s | contact at 27.733 s | **pass** |
| report 9 10.0-12.5 s (negative) | no contact, 959 4-9 m behind 555 | adjacent from 10.4 s, yaw step at 10.833 s: "possible unregistered contact" (would read "contact" with no telemetry) | **fail** |
| report 13 0-3 s | none: **wrong window** (see the correction under Round 4) | silent: the masks never get within 35 px | **not evidence** |

- **Negative on report 9 fails.** In a chase view the car behind overlaps the car ahead in the picture at 4-9 m, so the masks touch at 1 px for 1.5 s with no contact. The yaw step is the purple car cornering (axis angle -78 to -5 degrees over 0.6 s, noisy frame to frame), and 150 deg/s over 3 frames is under that noise. The rule's three parts cannot tell a bend from a spin on one camera angle. With telemetry the verdict is a flag, not a contact, which is the designed behaviour. Without telemetry it is a false contact.
- **A relative-yaw fix (heading change minus the other car's) was tried and reverted.** It did not clear the report 9 negative, because the chase camera turns with the black car, so only the purple car appears to rotate. It was written after seeing this clip, so the clip was no longer a held-out test. Kept out.
- **Report 13 0-3 s was the wrong window.** I read the bracket from the incident-count jumps (te 1375-1378) instead of from the offset table, whose contact is te 1387-1388 = clip 11.5-12.5 s. Silent here says nothing about the rule. Round 4 re-runs it on the right window.
- **What it means for the claim.** One positive (report 9, 0.1 s truth), one clean negative failed, and a wrong-window report 13 that is not evidence. The rule's contact claim holds when the consequence is a spin or a gap reopening on a close camera. It does not hold up as an adjacency-plus-yaw rule on chase footage without telemetry. A fix needs a second signal that tells a bend from a spin (for example the yaw rate against the track curve, or a speed collapse in the victim); that is not built.

## Round 3: more samples (Brock's go, 27 Oct)

Eight windows were planned from the key: three on report 15 (lap-1 contact 4134-4135 s, lap-2 contact 4341.0-4343.5 s, a side-by-side stretch 4205-4208 s, offset 3808.5 +- 1.5 from W0-01), one on report 46 (1139.4-1142.4 s, after the 1139.333 cut) and four report 9 negatives (959 4-9 m behind 555, no contact).
All eight first-frame box calls ran. Only the four report 9 negatives were tracked.

| Window | Truth | Rule says (no telemetry, and with silent telemetry) | Verdict |
|---|---|---|---|
| report 9 2.0-4.5 s | no contact | adjacent for 3 frames, not proven | pass |
| report 9 8.0-10.5 s | no contact | silent | pass |
| report 9 14.0-16.5 s | no contact | silent | pass |
| report 9 20.0-22.5 s | no contact | silent | pass |

Negatives overall: 4 of 5 pass (the fifth is 10.0-12.5 s above, where the cars sit side by side at 1 px for 1.5 s and the follower corners).
The failure needs close following plus a bend, so it is a specific shape, not a general noise rate: only 2 of the 5 windows had any adjacent frames at all.

**Report 15 and report 46 were not tracked, and that is a finding.**
- Report 15 is an in-car (cockpit) view. The contact is the camera car's own, and the camera car is never a mask, so a two-mask rule has nothing to measure. The boxes found 7, 3 and 3 cars ahead, none of them one of the pair. Own-car contact needs an own-car signal (camera shake, speed collapse, the telemetry bracket), not mask adjacency.
- Report 46 1139.4 is the wide reverse shot after the cut: seven small boxes in a pack, and I could not tell the orange car from the gold one by eye at that size. Picking blind would make the score meaningless.
The box calls for these four windows ($0.0025 each, $0.01 in all) are spent and kept, one folder per window, if a later pick is made.

**Positives still stand at one.** Report 9 27.733 s is the only clip with a sharp truth. The other brackets in the key (report 13 3 s wide, report 46 plus or minus 2 s) are too wide to call a hit or a miss, and report 15 cannot be measured by masks. A second positive needs either a new report 9-style clip with a visible pair and a 0.1 s truth sheet, or a wider tolerance agreed first.

## Round 4: looking for a second report 9-style clip

The corpus has no second clip with a 0.1 s truth sheet. What it holds, by use:

| Source | Truth | Usable for the rule? |
|---|---|---|
| report 13, clip 11.5-12.5 s | side by side te 1387-1388, phone recording, uncertain to 0.3 s (offset 1 s) | **yes, as a weaker positive** |
| report 10 stream, 1571-1572 s (report 1) | 44 passes 111 at te 177-178, offset 1394 plus or minus 1; no +4 | weak: already tracked (`r_report10_1570.0-1573.9`) |
| report 46 stream, 1141-1142 s | contact te 164-165, offset 977 plus or minus 2; +4 pair | weak: already tracked (`r_report46_1140.0-1142.0`) |
| report 15 | contact 4134-4135 and 4341.0-4343.5 | no: cockpit view, the camera car is never a mask |
| the two cockpit streams of [the two-camera experiment](../2026-10-27-identity-two-cameras/LOG.md) | none: no telemetry, a different sim | no |
| public steward-stream reviews (83 reviews, 597 spoken labels) | verdicts and spoken times, no telemetry | no: nothing sharper than the reviewer's words |

**Report 13 10.5-13.5 s** (picked from `first.jpg`: box 1 is the camera car #44 with its number visible, box 0 a sliver of the other car at the left edge, taken as #26): $0.0205, 90 frames.
- The masks touch (gap 1 px) from **11.7 s** to 12.5 s, which matches the batch-1 reading of 11.7-12.0 s.
- The rule asserts **contact at 11.933 s** (velocity jump, car 1): inside 11.7-12.0 plus or minus 0.3. **Pass.**
- It then asserts two more at 12.267 s and 13.0 s. The key gives no truth for them. The cars are side by side for a second and the partial mask of the second car changes area from 8.8k to 148k px, so they are probably mask changes, not contacts. They are unscored, and they are a precision problem: after a real touch the rule keeps asserting while the pair stays close.
- Fix kept: two adjacent runs that share one consequence are now one assertion (a flicker of the gap used to give the same contact twice). New test, red under mutation.

**Weak positives already on disk:** report 10 asserts at 1570.533 against a 1571-1572 s pass (0.5-1.5 s early, inside the 1 s offset error, and the key has no registered contact); report 46 asserts at 1140.267 against 1141-1142 s (0.7-1.7 s early, inside plus or minus 2). Both are consistent with the rule, neither proves it.

**Position now:** positives: report 9 (sharp, pass), report 13 (0.3 s truth, pass, with two unscored extras), report 10 and report 46 (weak, consistent). Negatives: 4 of 5 pass. Mask-based contact on a chase or broadcast view is workable. Cockpit footage needs another signal.

## Setup and models (for reuse)

- **Model:** SAM 3.1 (`sam-3.1`) only, through the metering proxy on this machine, endpoint `/v1/responses`, the d0 proxy (the token is read from the probe's settings and never printed).
  No language model was used anywhere in this task: the shot-cut gate and the rule are code.
- **Calls:** a box call (`input_image`, prompt "race car", $0.0025) on the first frame of a clip, then a video call (`input_video`, box prompts `<0f>1<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H|>,2<|box;...|>`, metadata `include_confidence=true`, `propagation_direction=forward`, `store=false`). A video call bills $0.0002 a frame with a 50-frame minimum.
- **Clip encoding:** ffmpeg 8.1.1 (full build) through `d3lib.encode_clip`, 30 fps, width 1280, crf 20; report 9 has its race-control chat box and driver-name panel blanked (`REPORT9_CHAT`, `REPORT9_NAME`).
- **Parser and tools:** `meta_sam_parser` 0.1.0 (pass `--with meta_sam_parser`), numpy 2.4.6, Python 3.14.3.
- **Rule constants:** adjacency 1 px for 3 frames, consequence window 0.5 s, yaw 150 deg/s for 3 frames, velocity jump 3x the median of the last 5 frames and over 120 px/s, reopen to 12 px, mask collapse 40%, area floor 250 px, cut margin 3 frames, cut threshold 0.10 histogram distance (32 bins, overlays blanked).
- **Call log:** `calls.jsonl` has one line per paid call: time, step, model, proxy, clip, window, prompt, picks, usage, estimated cost, seconds and the ledger total and sequence before and after. The first six lines (report 9, report 13 and the report 9 negatives) and the first report 15 box call are marked `reconstructed` because they ran before the logger worked; their usage is not captured. The later live lines match the ledger to the cent (the report 9 negative tracks 2 to 5: $0.015 each, ledger deltas 0.015).
- **Spend:** $0.156 in estimates across 20 calls (12 box calls, 8 track calls; 7 of the 20 are marked `reconstructed`), all within the $0.06 per-call cap and the metered budget. The fifth report 9 negative track moved the ledger total from 16.794 to 16.809, and the report 9 negative tracks 2 to 5 are ledger seq 691 to 695.
- **Mistakes in the harness, fixed:** a `\n` written as a real newline broke the script once (no spend); an undefined name after the first report 15 box call crashed the logger after the call had gone out (cost $0.0025, logged as reconstructed).

## Not done

- The by-eye cut list is not a truth set. A frame-labelled one is needed before the gate gets a pass mark (doc: 30 minutes per stream).
- One window, one contact: report 9 is a single case, so this is a smoke result, not a score. Rate on the 12 key cases needs more tracks.
