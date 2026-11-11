# Session record — 4 November 2026

## Scope

This session integrated a reviewability gate with the experimental racing review-window finder, checked whether fallback windows could be mistaken for incident findings, reviewed related public experiment results, and performed read-only live replay checks. The gate annotates candidate windows for reviewability; it does not decide whether an incident occurred.

## Changes in this task worktree

- Added `src/faultline/adapters/video/review_gate.py` and the `faultline-video review-gate` CLI path to classify review-window JSONL as reviewable, fallback-only/insufficient, or rejected input. The CLI refuses identical input and output paths.
- Integrated the gate into `faultline-video scan`: each emitted window retains its original fields and receives a `reviewability` annotation; scan output reports disposition counts. Insufficient candidates are kept so a later review pipeline can still inspect them.
- Added focused gate and scan integration coverage in `tests/adapters/test_review_gate.py`.
- Added `docs/review-candidate-gate.md` and updated README and racing page copy to explain the gate and its limits.
- Adjusted racing page copy to comply with its existing numeric-claims allow-list.

## Real footage check

Ran the scan locally against the available source videos for clips 1 and 13. It made no Meta or SAM calls. Each clip emitted one candidate and both candidates were marked `insufficient` / `fallback_only`:

| Clip | Candidate range | Anchor | Gate result |
|---|---:|---:|---|
| 1 | 1–7 s | 4 s | insufficient / fallback_only |
| 13 | 5–11 s | 8 s | insufficient / fallback_only |

The gate cannot tell that clip 1 has no incident or that clip 13's incident is around 10 seconds. It describes candidate reviewability only. `reject` is reserved for invalid, malformed, or out-of-range input; it does not mean “no incident.” The gate does not detect contact, infer an incident verdict, or remove fallback-only candidates from a downstream consumer. No manually supplied incident timestamps were added.

The implementation was checked against public experiment results. The available mask and contact measurements do not support a defensible automatic no-incident threshold, so the gate does not treat them as one.

## Forklift impact

No forklift detector, rule, adapter, stored record, dataset, or ruling was changed. The only project-surface copy change in this task is the racing explanation in `site/index.html`. A read-only replay of the live featured forklift case matched its stored record and all four rulings; rebuilt and shipped record hashes were identical (`c82ca137cb2c1b8b9415e7a0bd6befa344554dea8fbb30c44fef7c22d08c5044`). The replay completed in 43.36 seconds. This was a replay of saved inputs, not a new model run and not a write to the site.

## Live racing replay checks

Read-only replay requests to the live site returned matching stored and rebuilt results:

- Protest 1: `match: true`, both arms matched, 1.06 seconds; stored steward review S21.
- Protest 18: `match: true`, both arms matched, 1.04 seconds; stored steward review S21.

These endpoints replay saved inputs with model calls disabled. No fresh model calls were made and no records were modified. The subsequent health check returned `ok: true`, queue 0, running 0, serving commit `e25ba70ab75e4a7e68cc6c40b7bfeb73bb9273af`.

## Verification

- Focused tests: `uv run --extra site pytest -q tests/adapters/test_review_gate.py tests/test_site_page.py` — **40 passed in 0.33s**.
- Lint: `uv run ruff check .` — **All checks passed!**
- Format: `uv run ruff format --check` on the three changed Python files — **3 files already formatted**.
- Generated counts/log: `scripts/tally.py --write` and `scripts/build_log.py --write` were run; both corresponding `--check` commands passed.
- `git diff --check` passed.
- Full suite: **56 failed, 1020 passed, 32 skipped, 1 warning in 222.04s**. Fifty-five failures cascade from the absent ignored fixture `tests/fixtures/site_sweep/page/data/index.json` in this clone. The remaining failure is `tests/test_public_tree.py::test_no_private_media_or_feed_outside_assets`, triggered by pre-existing untracked diagnostic images in `build/moment-candidates/` (`1-candidates.jpg`, `15-candidates.jpg`, `18-event.jpg`, `24-candidates.jpg`). Those images were left untouched. The focused site-page run passed after the racing copy was adjusted.

## Git and deployment state

The implementation and this session record are in the existing task worktree on branch `task/yes-exactly-i-m-pretty-sure-that-s-what`, based on `master`. The task worktree has not been committed, merged, pushed, or deployed. Its existing untracked `build/` diagnostic artifacts were left untouched. The live site still serves commit `e25ba70ab75e4a7e68cc6c40b7bfeb73bb9273af`.

The separate candidate-gate task and the other pre-existing open site work remain open; no worktree was closed or discarded in this session.
