# The steward panel (27 Oct 2026)

## Question

Does a prosecutor, defence and judge panel rule better than one steward call?
The baseline is the single-agent Spark 1.3 rulings on the same five clips (Discovery 3, W1-01).

## Method

- Clips: reports 9, 1, 10, 46 (1280 px, 22 frames at 1.5 s) and 13 (360 px, 45 frames), with the same masks, windows and report wording as W1-01.
- Roles: the prosecutor and the defence each see the frames and the report and write a brief.
  The judge sees the frames, the report and both briefs, and rules.
  The role prompts are the ones from run 12 of the steward-limits experiment.
- Every frame is labelled with its video second in the text.
- Output limit 16,000 tokens, temperature 0, a separate case reference on every call so the proxy cache cannot answer.
- Three setups:
  - A: Spark 1.3 in all three roles.
  - B: Spark Open on Baseten in all three roles.
  - C: Spark Open as prosecutor and defence, Wonder as judge.
- Scoring: `L.score_ruling` against the answer key, as in W1-01.
- The script (`panel7.py`), the per-setup results and the raw replies stay with the private tooling and are not in git (the judges' free text can quote on-screen names).

## Result

Key verdicts: penalty on 9, 1, 46 and 13; no penalty on 10.
"Roles" means offender and victim both right.

| Setup | Verdict right | Roles right | Timing within 1 s | Cost for 5 clips |
|---|---|---|---|---|
| Single Spark 1.3 (W1-01) | 2 of 5 | 1 of 5 | 4 of 5 | $0.29 |
| A: Spark panel | 3 of 5 | 3 of 5 | 2 of 5 | $0.70 |
| B: Spark Open panel | 1 of 5 | 1 of 5 | 2 of 5 | $0.82 |
| C: Spark Open counsel, Wonder judge | 3 of 5 | 2 of 5 | 3 of 5 | $1.83 (judge alone $1.28) |

The single-call $0.29 is the five scored W1-01 rulings; Discovery 3's $0.345 for W1-01 also counts a report-13 call that reasoned to its 8,000-token ceiling and returned nothing.

Per clip, panel verdict then offender:

| Report | Single Spark | A | B | C |
|---|---|---|---|---|
| 9 | penalty, #559 (wrong) | penalty, #959 | racing incident | penalty, purple car, number not read |
| 1 | no action | no action | racing incident | racing incident |
| 10 | penalty on #555 (wrong) | racing incident | no action | racing incident |
| 46 | no action | racing incident | racing incident | racing incident |
| 13 | penalty, #44 | penalty, #44 | no action | penalty, #44 |

## What it shows

- Reports 1 and 46 failed in every setup.
  The contact is not visible to any role, so the judge has nothing to weigh.
  A panel cannot argue for a touch that no frame shows.
- Panel A fixed two single-agent errors: the purple car's number on report 9 (959, not 559) and the wrong offender on report 10.
  It cost 2.4 times the single call.
  This is one run per cell on five clips, so it is a lead and not a proof.
- Panel B lost to the single call.
  Spark Open wrote 4,000 to 15,000 output tokens per role and ruled "racing incident" or "no action" on all five clips, which is the cautious answer.
  It also saw contact sheets, not separate frames (see deviations), which probably cost it the number reads.
- Wonder as judge helped on report 13: it picked the first passage of the incident (0.5 s from the key) where Spark picked the second (24 to 26 s late).
  It cost 1.28 dollars for five judgements, about 0.26 each.
- Timing got worse than the single call on reports 1 and 46 in every setup (the single call was 0.0 s and 1.0 s off).
  I did not test why.
  Keep timing from the single call or from SAM, as W1-01 and W2-03 found.
- Run 12 in steward-limits found the panel better argued but no more correct, and this run agrees on the second half: it did not reliably produce a more correct ruling.

## Decision for the design

- Do not run the panel on every report.
- Run it as an appeal tier after the single call, only where the single call and the human steward disagree, with Spark as counsel.
- A Wonder judge is worth testing on appeals only, at about 0.26 dollars a ruling.

## Deviations

- Baseten refuses more than 8 images ("Too many images: 22 (max 8)").
  Spark Open therefore saw labelled contact sheets: 2 by 2 tiles at 960 px for the 1280 px clips (6 sheets), 3 by 3 at 360 px for report 13 (5 sheets).
  Spark and Wonder saw separate frames.
  The comparison between B and A mixes the model and the input form.
- One Baseten call failed with a malformed-data-URL 400 (report 10, prosecutor).
  The first judge ruled without that brief, so both were run again and only the repaired pair is scored.
- Setup C reused B's prosecutor and defence briefs (same model, same prompts, same sheets), so its new spend is the five Wonder judgements.
- The output limit is 16,000 here and 8,000 in W1-01, so the single-agent baseline had less headroom.
- Report 13's key window covers only the first passage of the incident, so a judge that cites the second passage scores about 25 s late.

## Cost

| Item | Dollars |
|---|---|
| Setup A | 0.70 |
| Setup B (including the repaired pair) | 0.82 |
| Setup C new calls (Wonder judge) | 1.28 |
| Total, proxy ledger | about 2.80 |

The estimate before the run was about 3.50 in total.
Setup B cost 0.82 against an estimate of 0.25, because Spark Open spends many thousand reasoning tokens on every call.
The probe ledger stood at 13.82 before this experiment and 16.67 after, under the 20 dollar cap.
The 2.85 difference includes calls from other runs on the same token, so the 2.80 above is the sum of this experiment's own priced calls.
