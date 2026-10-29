# Round 4: abstention (28 Oct 2026, overnight)

## Question

Does any signal keep wrong passes among shipped rulings at or under 1 at a usable coverage?
The signals are Spark Open's self-consistency (sampled votes, paraphrases, ablations) and the deterministic columns already on disk.
Everything under "Fixed before any run" was committed before any script read a signal or any paid call was made.

## Fixed before any run

### Definitions

- **Key.** The 58 cleaned racing cases of the [agreement-at-scale test](../2026-10-27-agreement-at-scale/LOG.md), human verdict.
- **Split.** A hash of each label id: calibration 26 cases (20 ruled), held-out 32 (24 ruled).
- **Shipped ruling.** The agreement test's temperature-0 ruling, the one the pipeline ships today.
  Its 14 no-rulings are abstentions by construction.
- **Wrong pass, narrow (WP).** Human penalty, shipped no_action: 5 of 44.
- **Wrong pass, broad (WP+).** Human penalty, shipped racing_incident or no_action: 13 of 44.
- **Asymmetric loss.** Per case: WP+ 3, wrong fail 1, abstain 0.5, correct 0.
- **Usable coverage.** At least 40% of the cases in the set.
- Wilson 95% intervals throughout; the minimal detectable difference is about 12 points at n = 58 and 17 at n = 29.

### A free retrospective first, and the gate on the paid run

Do the disagreements already on disk predict the misses?
Two sources: the [50-case panel test](../2026-10-27-panel-50/LOG.md) (Spark 1.3, single call against panel) and the two pilot rounds of the agreement test (Spark Open, uncropped against cropped, 20 cases).
The paid run goes ahead only if either source shows accuracy on the agree set at least 10 points over the disagree set.

### The perturbation run (cap $13 in code)

Spark Open, 12,000 tokens, on the agreement test's own frames, ten calls per ruled case:

| Arm | Calls | Temperature | What changes |
|---|---|---|---|
| s1 to s5 | 5 | 0.7 | Nothing but a nonce line |
| p1, p2 | 2 | 0 | The ruling instruction paraphrased, checked by a separate reader for the same rules and no verdict hint |
| a1 | 1 | 0 | Every frame label shifted by +1000 s |
| a2 | 1 | 0 | One irrelevant line: "Weather for this session: clear and dry, track temperature 24 C." |
| r1 | 1 | 0 | Nothing but a nonce line: the temperature-0 noise floor (added as a deviation, run last) |

Every call carries a nonce so the proxy cache cannot answer.
Before each call the runner sums its own matched ledger lines and stops when the next call would pass the cap.

### Scoreboards

- **Abstention tournament.** Every candidate abstain rule (deterministic: contact time given, cars identifiable, stated confidence; model: sample agreement, all-call agreement, paraphrase and ablation stability, a penalty veto; and pairs) is scored on calibration by the loss, the best is fixed, then scored once on held-out.
  The answer is yes only if that rule keeps WP at or under 1 on held-out at usable coverage.
- **Conformal threshold** on all-call agreement, calibrated to a 20% per-case WP+ risk, applied to held-out, then swapped.
- **Signal marks:** AUROC of sample agreement at least 0.65; Brier of the penalty share under the constant; ablation flips at least 10 points over repeat flips; at least 90% of calls finish; at most $0.30 a case.

## Results

### The free retrospective ($0)

| Source | Agree set right | Disagree set right | Gap |
|---|---|---|---|
| 50-case panel test (32 agree, 18 disagree) | 37.5% | single 33.3%, panel 44.4% | -6.9 points |
| Agreement test pilots (6 agree, 14 disagree) | 33.3% | 21.4% | +11.9 points |

Within Spark Open, the 7 cases where both pilot rounds ruled and differed were all wrong in round 1.
That passes the gate on the pilot rounds only, at tiny n, so the paid run went ahead.

### The perturbation run

440 of 440 calls returned; 434 (98.6%) finished with a verdict.
Cost by the ledger: **$10.1485, $0.231 a case**, under the $13 cap.

**The answer: no.**
The rule the tournament chose on calibration (no penalty veto, contact time given and cars identifiable) keeps WP at 0 on held-out, but keeps only 2 of 32 cases (6%).
The conformal threshold holds WP at 1 on held-out at 69% coverage, but at 36% agreement, no better than shipping everything, and swapped it lets 3 wrong passes through.

Why: the wrong passes are confident, not noisy.

| Case | Shipped | Stated confidence | The 10 calls |
|---|---|---|---|
| 391 | no_action | 0.84 | N N N N N N N N N N |
| 452 | no_action | 0.72 | N N N N N N N N N N |
| 502 | no_action | 0.82 | N N N N N N N N N N |
| 335 | no_action | 0.62 | N N N N N N N R N N |
| 410 | no_action | 0.62 | R R R R R R R R P R |

Three of the five narrow wrong passes are no_action on every call, so any rule that keeps unanimous rulings ships them.

| Signal | Result | Met |
|---|---|---|
| AUROC of sample agreement at least 0.65 | 0.642 (bootstrap 0.46 to 0.80) | **no** |
| Brier of the penalty share under the constant | 0.288 (constant 0.242) | **no** |
| Ablation flips at least 10 points over repeat flips | 38.6% against 29.5%, 9.1 points | **no** |
| At least 90% of calls finish | 98.6% | yes |
| At most $0.30 a case | $0.231 | yes |

- Stated confidence ranks right against wrong (AUROC 0.675) as well as ten calls of sampling (0.662), at no cost.
- **A temperature-0 repeat does not reproduce the shipped ruling.** The r1 repeat changed 12 of 44 verdicts (29.5%).
  The data cannot separate provider nondeterminism from sensitivity to the nonce line; either way, one call is not a stable ruling.
- The +1000 s time shift moves verdicts 18 points more than a repeat, so the model reads frame labels that carry no meaning for the verdict.
- Penalty is 18.2% of all 440 votes, so sampling does not cure the penalty aversion.
- Ranked by all-call agreement, WP stays at 3 or 4 down to 20% coverage.

Self-consistency is a weak ranker and cannot remove wrong passes.
Abstention has to come from measured evidence quality or a human seat, never from the model's own spread, and the README carries no model-derived confidence number.

## Follow-ups (same day, $0 unless stated)

### 1. Penalty voting

A lead from the table above: on three broad wrong passes (165, 525, 536) most calls say penalty and the shipped ruling does not.
Not blind, so a pass is a lead only.
The rule chosen on calibration was "ship penalty if any one of nine calls says penalty", and it passed its four marks both ways: held-out WP+ fell from 6 to 1 and agreement rose from 9 to 12 of 32.
But a constant penalty on every ruling beats it on loss, and on the 58 it fixes 7 wrong passes while adding 8 wrong penalties.
Six of the 13 broad wrong passes get no penalty vote at all.

### 2. Random-flip control

Do those flips find human-penalty cases better than the same number of flips at random (10,000 draws)?

| Set | Flips | Fixed by the vote | Fixed at random (mean) | p |
|---|---|---|---|---|
| Calibration | 4 | 2 | 1.87 | 0.665 |
| Held-out | 11 | 5 | 3.14 | 0.098 |
| All 36 not-penalty rulings | 15 | 7 | 5.42 | 0.220 |

**No.** The gain is the penalty base rate: the shipped ruling says penalty on 8 of 44, the humans on 18.
The paid replication of penalty voting is off.

### 3. Brock's check of the four confident misses

Brock watched 335, 391, 452 and 502, and all four labels hold as penalty, so nothing is rescored.
On 335 the penalty belongs to the car that hit the driver the clip follows, a point the verdict-only key does not score.
Every one of the four shipped rulings reasons "no contact visible, so no action"; on 452 the model saw the rejoin and still ruled no action, so that miss is rules knowledge, not vision.

### 4. A ruling prompt with non-contact penalties (cap $3)

The shipped sporting code ends "no contact is no action".
One sentence was swapped: a penalty does not need contact (an unsafe rejoin, forcing a car off, or making a car leave the track or lose control to avoid you).
Two temperature-0 runs (c1, c2) on the 44, 88 calls, **$2.5264** by the ledger.

| On the 44 ruled | Agree | WP | WP+ | False penalties |
|---|---|---|---|---|
| Shipped | 16 | 5 | 13 | 3 |
| r1 (old prompt, nonce) | 14 | 6 | 13 | 5 |
| Penalty on every ruling | 18 | 0 | 0 | 26 |
| c1 (new prompt) | 18 | 5 | 12 | 5 |
| c2 (new prompt, repeat) | 19 | 7 | 10 | 8 |

All four marks fail on c1, and three of four on c2: false penalties rise faster than wrong passes fall, and all four confident misses stay no action on both runs.
The wording does not go into the ruling prompt.
**The repeat noise is the bigger finding:** c1 and c2 differ only in the nonce label and disagree on 17 of 44 verdicts (39%), so every prompt-level difference measured on one run of 44 sits inside that noise.

## Cost

$10.1485 for the perturbation run (cap $13) and $2.5264 for follow-up 4 (cap $3), $12.67 in all, from the ledger.
The retrospectives and follow-ups 1 to 3 cost $0.

## What it does not prove

- n is 20 and 24 ruled cases a half; every half-level difference sits under the minimal detectable difference except the coverage collapse.
- The key is the cleaned two-reader subset of drafted labels; where a label is wrong, a wrong pass may be a right ruling.
- One model, one input shape, one sampling temperature.

## Needs

- Abstention by evidence rule (no identity, no contact measured, small cars) and no shipped confidence number.
- Any later prompt test on Spark Open needs at least three repeats an arm, because one run flips about a third of verdicts.
- A vision-side look at the four confident misses, and an offender field in the key before any identity claim is scored.
