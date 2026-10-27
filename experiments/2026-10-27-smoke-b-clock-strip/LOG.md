# Smoke test B: clock strip by template matching, and the offset solver

27 Oct 2026.
Pieces 5 and 6 of the deterministic-reads design, a private note not in this repo.
Scripts only: OpenCV and NumPy, no model, no network, $0.

## What was built

- `extract_crops.py` cuts the 20 W0-04 strip crops (`crop=270:40:0:88` at 1280x720) from the source videos with ffmpeg.
- `build_templates.py` cuts glyph templates from the ph10 crops, labelled by `eye_reads.json`, and writes `templates.npz` with a hash manifest.
- `strip_read.py` reads a crop: flag by median colour, LAP and TIME by finding the ink clusters and tiling each with templates (normalised cross-correlation, dynamic programme over left edge and glyph).
- `offset_solver.py` holds the constancy filter and the offset solver (TIME witness, LAP witness, refusal when they disagree by more than 2 s).
- `score_smoke.py` scores the reads against the eye reads; `run_smoke.py` runs everything and writes `results/results.json`.

## Result

| Check | Result | Pass mark |
|---|---|---|
| TIME digit-exact | 17 of 18 strips | 18 of 18 |
| LAP digit-exact | 17 of 18 strips | 18 of 18 |
| Flag | 18 of 18 GREEN | (not in the pass mark) |
| Clean feed read as no strip | 2 of 2 | 2 of 2 |
| Time a crop | 3.13 ms median, 9.51 ms max | under 10 ms |
| TIME plus stream second, SD after the filter | ph10 0.42, ph46 0.49 | 0.5 or less |

The crop times are the results file's; the first write-up gave the median as 3.2 ms.

The strict pass mark (18 of 18) is not met: one TIME and one LAP are wrong or empty, both on ph46 and both involving the digit 9.

- ph46 at 1566: TIME `16:29` read as `16:20`, a wrong read, not an empty one.
- ph46 at 1822: LAP `L9` read as nothing (TIME `12:13` read right).
- The constancy filter catches the wrong read: TIME plus stream second is 2546 against a constant near 2555, so it drops out.
- The same filter drops ph10 at 1540, the stale `0:00 L9` overlay, as the piece predicted.
- After the filter every kept TIME is exact: 9 of 9 on ph10 and 7 of 7 on ph46.

## How the templates were cut, and what is held out

- Templates come from the ten ph10 crops only (greedy cover of the fewest crops did not carry a 9 on TIME).
- ph46 is held out: none of its 10 crops fed a template, so its 8 strips are a transfer test from one track to another.
- The 9 has two real templates (from the two `L9` lap crops) plus three derived by turning each 6 half a turn (this changed no read).
- ph10's own TIME never shows a 9, so no TIME 9 was ever cut from the same strip; that is the one gap.
- Three crops were expected; four to ten were needed because ten glyph classes had to be covered, and the 9 needed the lap font.
- Half-pixel phase copies of every template made it worse (15 of 18), so they are not in.

## Findings

1. **The strip is not at a fixed place.** TIME and LAP sit right of the track name, so a strip with a short name (Cadwell Park) puts them about 25 px left of one with a long name (Oulton Park Circuit).
   The first version, with fixed windows from ph10, read 3 of 20.
   TIME and LAP are now found by ink clusters from the right, and TIME decodes with a free left edge because on a short name it starts about 2 px after the track name ends.
   The doc's "crop at its fixed place" holds per track, not per broadcast; the crop itself (`270:40:0:88`) still holds.
2. **LAP is centred, TIME is left-aligned.** `L1` and `L16` share a centre; `0:00` and `38:43` share a left edge.
3. **ph10: the strip's TIME and the replay's `timeRemain` disagree by 166 s.**
   Strip TIME plus te is 2565; replay `timeRemain` plus te is 2399.
   The first replay frame is te 166, which is the same number, so a recording-start offset is the likely cause (not checked).
   Because of it the solver's TIME witness gives 1560 for ph10 while the hand offset is 1394, and the LAP witness brackets it to 1373 to 1421.
   The solver refuses, naming a 139 s disagreement, as the piece says it should.
   So the piece-6 smoke test as written ("from the eye-read TIME values and the ph10 replay's timeRemain, the ph10 offset must come out 1394 plus or minus 1") **fails**; the offset comes only from the lap and event witnesses on that stream.
4. **ph46: the TIME witness gives 977.0 from 7 kept reads**, the hand offset is 977 plus or minus 2, and the replay's `timeRemain` equals the strip clock there.
   The LAP witness brackets 920 to 1021 on its two bracketed changes, which agrees.
5. **The LAP witness alone is coarse.** Three lap changes bracket ph10 to a 48 s band, so it is a cross-check, not an offset.

## Not verified

- Flags other than GREEN: all 18 strips are green, so YELLOW, WHITE and chequered colours in `strip_read.py` are nominal values, not measured.
- A clock past an hour (`1:05:30`): the parser takes `m:ss` or `mm:ss` only.
- Any broadcast package other than this league's.
- Whether a TIME 9 template cut from a real TIME strip fixes the two ph46 misses; the crops that would give one (ph46) are the held-out set.
- The cause of the 166 s on ph10.

## Files

- `templates.npz`, `templates.json`: glyph images and hashes; no names in them.
- `results/results.json`: every read against its eye read, per-stream solver output.
- These files and the scripts stay with the private tooling; the 20 crops are rebuilt by `extract_crops.py` and are not in git.
