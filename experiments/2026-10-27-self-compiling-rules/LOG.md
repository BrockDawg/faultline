# Self-compiling rules: a rulebook compiled into a rules pack by Spark Open (27 Oct 2026)

## Question

Can a model turn a flat league rulebook into a rules pack the loader accepts and a steward can use, without a person splitting and naming the rules first?
A rules pack is a folder of markdown rule files, each with an `id` and a `title`, plus a `pack.json`.
The loader is the one in this repo (`faultline.pack.load_pack`).
The hand-written pack for each source is the pack a person made from the same rulebook.

The headed arm is a control: it hands the model the rulebook's own headings and split, so it measures copying and cannot fail on structure.
Only the flat arm tests whether the model can find the structure.

## Result

| Source | Arm | Samples that finished and loaded | Units kept verbatim | Invented | Rules made (hand pack has) | Grade mark (80% same or better) |
|---|---|---|---|---|---|---|
| Public library rulebook (oval) | headed | 3 of 3 | 86 of 86 | 0 | 20 (20) | 20 of 20, met |
| Public library rulebook (oval) | flat | 3 of 6 over two passes | 86 of 86 in each that loaded | 0 | 18, 17, 18 (20) | 14 of 20, not met |
| League A | headed | 3 of 3 | 55 of 55 | 0 | 11 (11) | 11 of 11, met |
| League A | flat | 3 of 3 | 55 of 55 | 0 | 13, 15, 13 (11) | 9 of 11, met |
| League B | headed | 1 of 6 over two passes | 184 of 297 | 2 | 10 (10) | 1 of 10, not met |
| League B | flat | 2 of 5 over two passes | 185 of 297, and 54 of 297 | 2 | 10 and 9 (10) | 0 of 10, not met |

Where a sample finished, copying was exact on the two short rulebooks: no line dropped, none invented, no bold mark or placeholder lost.
The one long rulebook, league B, was condensed instead of copied.
The model spent 7,200 to 39,900 tokens on a job whose answer is 2,500 to 4,000 tokens, and 11 of 26 compile calls ran out of room.

## Method

- Sources: three rulebooks, each its own run and never pooled.
  The public library `oval` rulebook (20 rules, 86 bullets), league A (11 rules, 55 units, 9 rules in bullets and 2 in prose) and league B, a PitBot league (10 rules, 297 sentences, all prose).
- Arms: headed gives each rule's title as a `##` heading, with its bullets or sentences under it.
  Flat gives every unit in order, one per line, with no titles, no ids and no blank lines.
- Model: `meta-models/muse-spark-open-1026` on Baseten, through the metering proxy, three samples per arm, temperature 0.2.
- Prompt: return one JSON object holding the pack fields and the rules, copy every bullet or sentence exactly, add nothing, drop nothing.
  It names no hand pack, no rule count and no ids.
- Writing the pack: code writes the files from the JSON and runs `load_pack` on the result.
  The model never writes a file.
- First try: a sample succeeds only if the JSON parses, the files render and `load_pack` passes with no error.
  One repair call is allowed on a parse or load error.
  A call that ends on `length` is never scored and never repaired.
- The unit is a bullet when a rule has marked bullets, otherwise a sentence.
- Checking: code compares units, not rules.
  A hand unit counts as kept only if it is equal after stripping bullet marks, bold marks and spacing.
  A nearly equal unit is listed as reworded, never as kept.
  A compiled unit with no hand match at 0.60 similarity is invented.
  Code also checks every bold span and every `[placeholder]`, flags a changed negation or number, and maps each hand rule to the compiled rules that hold its units (same split, merged, split).
- Marks, fixed before the run, per arm: loads on the first try in 3 of 3 samples, zero invented units, at least 95% of units kept verbatim, no bold span or placeholder lost, and at least 80% of the hand pack's rules graded `same` or `better`.
- Passes: pass 1 allowed 13,936 tokens at most per call, pass 2 allowed 21,936 and pass 3, league B only, 39,936.
  Each pass is reported apart and a failed sample is never replaced silently.
- Grading: Muse Wonder (`muse-wonder-1.0`) graded sample 1 of each arm, or the first sample that finished, as `same`, `better`, `worse`, `wrong` or `different-split`.
  Code sets a floor after the model answers.
  A rule with a missing, invented or negation-changed unit is forced to `wrong`.
  A rule with any other reworded unit, or a lost bold span or placeholder, is capped at `worse`.
  A merged or split rule is `different-split` unless the model said `better` and every other flag is clean.

## Findings

### 1. Copying is exact on short rulebooks, wherever the answer finishes

Every sample that finished on the oval and league A rulebooks kept 100% of the units verbatim, with 0 invented units, no flipped negation, no changed number and no lost bold span or placeholder.
That holds for both arms and for all three samples of the headed arm.

### 2. Finding the structure is the flat arm's real test, and the two rulebooks went opposite ways

- On the oval rulebook the flat arm merged rules: 17 or 18 rules for 20, with 4 to 6 hand rules merged into a neighbour.
  Wonder graded 14 of 20 rules `same` and 6 `different-split` on the sample it graded.
- On league A the flat arm split rules: 13, 15 and 13 rules for 11.
  Sample 1 kept the same split on 9 rules and split 2.
  Samples 2 and 3 kept the same split on 6, merged 1 and split 4.
  Wonder graded 9 of 11 `same` and 2 `different-split` on sample 1.
- Titles and ids rarely matched the hand pack in the flat arm: 3 to 6 of 20 on the oval rulebook, 3 to 5 of 11 on league A.

### 3. Long prose was condensed, not copied

League B is 297 sentences of prose, 3.5 times the oval rulebook's units.
The model finished 3 of 11 samples, and each of those lost much of the text.

| Sample | Units compiled (of 297) | Verbatim | Reworded | Missing | Invented | Negations changed | Numbers changed |
|---|---|---|---|---|---|---|---|
| headed, pass 3, sample 4 | 228 | 184 | 42 | 71 | 2 | 3 | 7 |
| flat, pass 2, sample 3 | 229 | 185 | 42 | 70 | 2 | 3 | 7 |
| flat, pass 3, sample 4 | 97 | 54 | 41 | 202 | 2 | 3 | 7 |

All three loaded as valid packs with fluent text.
Only the unit-by-unit check shows that a quarter to two thirds of the rulebook is gone, and that three sentences now say the opposite of the source.
The two long samples share the same 42 reworded, 3 negation and 7 number changes, which points to one condensing pattern, not random drift.
This test mixes length and prose, so it does not say which of the two causes it.

### 4. The token budget is a large part of the cost and of the failures

| Pass | Output ceiling per call | Calls | Ended on `length` | Cost |
|---|---|---|---|---|
| 1 (oval) | 13,936 | 6 | 2 | $0.3028 |
| 2 (oval flat, league A, league B) | 21,936 | 15 | 6 | $1.1353 |
| 3 (league B) | 39,936 | 5 | 3 | $0.7447 |
| Grading (Wonder) | 19,936 | 6 | 0 | $0.5113 |

Completed compile calls used 7,211 to 26,336 output tokens.
Raising the ceiling from 13,936 to 21,936 turned some oval flat failures into packs but did not fix league B.
Going on to 39,936 let two more league B samples finish, and both were lossy.

### 5. The model grader flattered the model's own family, and the code floor caught it

Wonder is in the same model family as the compiler.
On league B it graded 8 of 10 rules `same` for the flat sample and 10 of 10 for the headed sample.
Those packs were missing 70 and 71 of 297 units.
The floor changed 9 of 10 grades on each sheet to `wrong`, and the final grades read 0 of 10 and 1 of 10 `same` or `better`.
Without the floor the league B headline would have read 80% and 100%.
On the oval and league A sheets the floor changed nothing, and Wonder's grades agreed with the code's flags.

## Cost

- Compile calls: 26 calls, $2.1828 by the proxy ledger, none from the cache.
- Grading calls: 6 calls, $0.5113.
- Total: $2.6941.
  Spark Open is billed from the Baseten credit and Wonder from the Meta credit.

## Limits

- One run per source and arm, three samples at most per arm, so the marks are counts of samples, not rates.
- The oval rulebook is public library text the model may have seen in training, so its scores are an upper bound.
- Only one sample per arm was graded, and only by Wonder with a floor set by code.
  Nobody has yet read the listed spot-check blocks by hand.
- The floor stops a same-family grader from upgrading a flagged rule, but it cannot stop it from marking an unflagged rule `same` when a person would not.
- A nearest-match score of 0.60 separates reworded from invented, and a different cut-off would move a few units between the two classes.
- The sentence splitter does not split after a short list of abbreviations, so a sentence that really ends on one is joined to the next.
  Both sides use the same splitter, so they still match each other.
- League B's run mixes two causes, length and prose, and no short prose rulebook was run.
- The flat arm ran at three different ceilings across passes, and the pass 1 failures on the oval rulebook came from the ceiling, not from the answers.

## What it means for the steward

- A compile step is usable as a first draft for a short rulebook, provided code checks every unit afterwards and rejects any pack below 95% verbatim.
  The check, not the model, decides whether the pack goes live.
- A pack must never be accepted because it loads: league B's packs load and are wrong.
- Whether compiling a long rulebook section by section fixes the condensing is tested in [Self-compiling by section](../2026-10-27-self-compiling-by-section/LOG.md).
- A model grader of the same family needs the code floor, and it should never be the only gate.

## Files

- The compile, check, sheet and grading scripts, the oval packs, the call records, the check reports and the grading sheets are kept with this experiment's private record.
- The league runs are kept with the private record too, and never enter git.
