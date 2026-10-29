# Self-compiling a long rulebook by section (27 Oct 2026)

[Self-compiling rules](../2026-10-27-self-compiling-rules/LOG.md) compiled league B's 297-sentence rulebook in one call and got a condensed pack.
This run cuts the rulebook at its headings, compiles each section on its own and joins the packs by code.
The paid steps are Spark Open compile calls through the metering proxy, on Brock's go.

## Question

Does compiling a long prose rulebook one section at a time stop the model condensing it?

## Marks (written before any paid call, never changed after)

One run, one sample.
The rulebook is league B, a PitBot league's 297-sentence prose rulebook, in 10 sections of 1, 14, 29, 11, 13, 9, 29, 5, 125 and 61 sentences.
The joined pack passes only if all four of the earlier experiment's marks hold:

| Mark | Pass line |
|---|---|
| Loads on the first try | All 10 section calls load with no repair, and the joined pack loads |
| Invented units | 0 in the joined pack |
| Kept verbatim | At least 283 of 297 (95%) |
| Bold spans and placeholders | None lost |

- A unit is a sentence, compared as before: equal after stripping bullet marks, bold marks and spacing is kept, a nearest match at 0.60 or better but not equal is reworded, no match is missing, and a compiled unit with no match is invented.
- Reported, not marks: reworded and missing counts, negations and numbers changed, how the compiled rules map onto the hand rules, tokens per section and rules made.
- Baseline from the whole-rulebook run, headed arm: 184 of 297 verbatim and 2 invented in the one sample that finished; the flat arm kept 185 and 54.
- A call that ends on `length` is never scored and never repaired; one re-run of only those sections is allowed at a higher ceiling, reported as its own pass.
- A pass on one sample says the method can work on this rulebook, not how often it does.
- No Wonder grade: the marks are the code marks only.

## Method

- Source: league B's hand pack taken apart into the headed rulebook by the earlier experiment's own code, then cut into one block per rule, its `##` heading and its sentences.
  The headings are the same ones the earlier headed arm handed the model, so this run changes the chunking and nothing else.
- Model and prompt: `meta-models/muse-spark-open-1026` on Baseten, temperature 0.2, the earlier compile prompt unchanged, one section per call.
- Ceiling: `max_tokens` 14,000, which the provider raises by 7,936 for reasoning, so 21,936 output tokens a call at most.
- Writing and joining: code writes each section's files, loads them with `faultline.pack.load_pack`, then joins the loaded sections' rules in order.
  A repeated rule id gets the section number added by code, and the count is reported.
  The model never writes a file.
- Checking: the earlier check scores the joined pack, and the same comparison runs on each section against its own hand rule.
- Cost estimate: 10 calls, $0.95 at the ceiling, $1.89 if every call needed a repair.
- A free test with fake answers made 10 sections and a joined pack of 297 of 297 units, all four marks passing.
  A drill with one section ending on `length` and one with a dropped and an invented unit showed the joined pack marked failed, the one-section re-run fixing it, and the section check counting the invented unit.

## Result

Run on 27 Oct 2026 in one pass of ten calls, with no repair and no `length` finish, so no re-run was needed.
**The joined pack failed two of the four marks.**

| Mark | Pass line | Result | Met |
|---|---|---|---|
| Loads on the first try | All 10 section calls, and the joined pack | 10 of 10 first try, joined pack loads | yes |
| Invented units | 0 | 2 | no |
| Kept verbatim | At least 283 of 297 | 198 of 297 (66.7%) | no |
| Bold spans and placeholders | None lost | 0 lost (the rulebook holds none) | yes |

Other counts, joined pack: 41 reworded, 58 missing, 3 negations changed, 7 numbers changed.
The model made 41 rules for the 10 hand rules (241 units out), and 2 repeated ids were renamed by code.
Seven hand rules were split over several compiled rules and three kept their split.

| Section | Hand units | Verbatim | Reworded | Missing | Invented | Output tokens |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 0 | 0 | 0 | 2,042 |
| 2 | 14 | 0 | 5 | 9 | 1 | 3,584 |
| 3 | 29 | 15 | 5 | 9 | 1 | 7,144 |
| 4 | 11 | 5 | 3 | 3 | 0 | 4,298 |
| 5 | 13 | 5 | 4 | 4 | 0 | 7,894 |
| 6 | 9 | 3 | 3 | 3 | 0 | 8,426 |
| 7 | 29 | 23 | 3 | 3 | 0 | 12,069 |
| 8 | 5 | 3 | 1 | 1 | 0 | 7,633 |
| 9 | 125 | 125 | 0 | 0 | 0 | 9,033 |
| 10 | 61 | 18 | 17 | 26 | 0 | 13,817 |
| All | 297 | 198 | 41 | 58 | 2 | 75,940 |

- Against the whole-rulebook headed run (184 of 297 verbatim, 2 invented): 14 more units kept, the same 2 invented, the same 3 negation and 7 number changes.
- Section 9, the largest at 125 sentences, copied exactly, while section 10, at 61, kept 18.
  So length inside a section does not decide the result.
- Unit by unit, all 41 sentences reworded here were reworded in the whole-rulebook run, and all 58 missing here were missing there too (that run lost 71).
  Chunking gave back 13 of the lost sentences and changed nothing else.
- Sections 2 to 8 and 10 lost between 10% (section 7) and 64% (section 2) of their sentences, with every call ending on `stop`, so the model chose to stop; it did not run out of room.

## Cost

- 10 Spark Open calls, 7,203 input and 75,940 output tokens, $0.3317 by the proxy ledger, Spark rows only.
  That is under the $0.95 ceiling.
- No Meta, SAM or Modal spend.

## What it does not prove

- It tests one sample of one rulebook.
  A second sample could land differently, though the 41 reworded sentences matching the earlier run exactly points to the sentences, not the dice.
- It does not say why those sentences are altered.
  Nobody has read the reworded and missing sentences by hand, so whether the model dropped, merged or corrected them is not known.
- Section 9's exact copy is not explained: it may be a more uniform kind of sentence, or a section the model finds easy to copy, and the sentence types were not compared.
- Whether the lost sentences were merged into others was not measured beyond the counts above.
- A shorter prose rulebook was not run, so length and prose are still two causes mixed in the earlier run, and only section length is shown not to matter here.
- No Wonder grade was run, so rule titles and splits are not judged by anyone.

## What it means for the steward

- Splitting by heading does not fix the condensing.
  The check, not the model, still decides whether a pack goes live, and this pack must be rejected.
- Per-section checking is a useful tool for the design: it names which sections copied exactly and which did not, so a failed section can be re-asked alone for the cost of one call.
- The design should not count on a model compile of a long prose rulebook, and a hand-checked step stays in the pipeline.

## Needs

- Brock to read the 41 reworded and 58 missing sentences and say what they have in common.
- A new experiment, if wanted, with its own marks: a prompt change aimed at that sentence type, or one sentence per call for the failed sections.
  This run's marks are closed and are not re-run.

## Files

The section compile, join and score script is kept with this experiment's private record, and reuses the earlier experiment's scripts unchanged.
The league text, answers and packs are kept with the private record too, and never enter git.
