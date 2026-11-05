# Final submission pass, 3 Nov 2026

This log records the judge-review fix pass on faultline, what was checked, and what it used.
It follows `docs/drop-2026-10-31.md`: one dated log per landing, with the spend stated in plain words.

## 0. Usage, for the totals

| What | Count |
|---|---:|
| Paid calls through this project's metering proxy made by this session | 0 |
| Paid calls to Baseten made by this session | 0 |
| Dollars added to the proxy meter (`tally.json`) by this session | $0.00 |
| Coding-agent model | Muse Wonder 1.0 (`muse-wonder-1.0`), a Meta model, called over the Meta API through Muse (Meta's CLI tool) — direct API use, not through this project's metering proxy and not a subscription |
| Coding-agent tokens (session usage report, owner-supplied 3 Nov) | Input 74,226,224; cached 71,767,322; output 268,774; total 74,494,998 |
| Coding-agent cost (estimated, same report) | $29.56 over 258 turns, no subagents; observers 260 completed (8,827,189 tokens) |
| Server-side script replays run (no model call in any of them) | 1 live worker check (screen capture), 1 shipped-set replay on the box, 2 graded-set replays on the box, 1 shipped-set replay locally |
| Site deploys to brockdev | 2 (the second with `--record`) |

At the time of this 3 Nov report, the running count's meter (`tally.json`) showed 9,362 paid calls and $139.51. It counts only calls routed through this project's metering proxy, and this session made none, so the proxy total was unchanged by this session.
This session's own model use was Meta API use all the same: Muse Wonder 1.0 through Muse, Meta's CLI tool, billed by the API and bypassing the proxy, so the proxy never saw it. The estimated $29.56 (74,494,998 tokens) is recorded separately in `meta-usage-adjustments.json`, sourced from this report.

## 4 Nov running-total update

The private ledger counter was refreshed on 4 Nov. It now reports 9,469 paid model calls and $143.68 through the project proxy. The README count keeps that proxy amount separate from the $29.56 direct Muse Code CLI estimate and shows their combined total, $173.24. The generated `tally.json` remains the proxy-ledger total; the adjustment file carries the separately sourced direct estimate.
The Meta models named in the new site traces (SAM 3.1 `sam-3.1`, Muse Spark Open `meta-models/muse-spark-open-1026`, Muse Spark 1.3, Muse Wonder 1.0) are read from the recorded replies already in the record; surfacing them made no new call.

One correction to the record: the four commits of this pass (`0d5539b`, `11e12cf`, `2331cdf`, `819d039`) carry the trailer `Built-With: claude-opus-5-5 via Claude Code`, filled in by the commit hook from a stale `faultline.builtWith` git config left by an earlier session.
They were in fact built by Muse Wonder 1.0 via Muse Code.
History is not rewritten to fix this; this log is the correction, and the commit that carries this log carries the right trailer itself.

## 1. The work, by fix-list item

Item 2, the 92-vs-110 shift number, resolved from `data/shift.json` on the live bundle: 48 windows, 240 rulings (16 breach, 84 clear, 140 unable); unable by missing fact: `camera.static` 110 (22 per rule x 5 rules; 22 windows unable on every rule), `contact.consequence` 16, `truck.moving` 6, `truck.speed_mps` 3, `truck.front_in_strip` 2, `truck.reversing` 2, `person.distance_m` 1.
110 is the ruling count; 22 is the window count; 92 matches nothing in the data.
README, the site, and the film now all say "110 of the 140 unable rulings (22 windows x 5 rules, each naming camera.static)".
No data was edited to match a graphic.

Item 4, README judge's path: a ten-line block above the scene tables (problem, hero domain, film/live/repo links, the replay one-liner, the three headline numbers, one test command, the refusals-and-scripts-decide line).
Inserting it moved every cited README line down ten, so `src/faultline/adapters/video/bundle.py`'s line citations and the two hardcoded line expectations in `tests/adapters/video/test_site_bundle.py` moved with it, and the bundle and racing data were rebuilt by their builders.

Item 3, site: judge's-path nav (film, live demo, replay, GitHub, headline numbers); hero case `blind_corner_no_vest_07` with its breach ruling and deciding number rendered on load; scoreboard immediately after the hero; shift still defaults to "To review" with the full breakdown one click deeper; SAM 3.1 and Spark Open traces rendered by `site/app.js` from the served clip JSON (recorded reads and notes, nothing fabricated); PitBot relabelled "The same judge, on the author's own league"; fallback copy now reads "stored ruling — live check unavailable" (and `tests/test_site_page.py`'s expectation with it).
The data contract (`data/index.json`, `data/racing.json`, `data/shift.json`, per-clip JSON, worker API) is unchanged.

Item 5, film: one re-export from the shipped master (not overwritten) into `demo/faultline-film-v2.mp4` and `demo/faultline-film-web.mp4` (both gitignored): clarified shift overlay, 6 s cut from the racing return, a 6 s real screen capture of the live "Check nobody changed it" replay (recorded headless against the live site; it ends "Same ruling. Nobody edited it.") inserted in the replay slot, and a capability caption over the closing panels.
`demo/SCRIPT.md` lines 12, 13, and 15 carry the same edits in words; `demo/captions-v2.srt` is the re-timed sidecar.
Web copy: 1920x1080, 177.4 s, 35,944,439 bytes, -16.4 LUFS integrated, true peak -1.04 dB (ffmpeg loudnorm measurement).
The spoken closing line still says the old words; only the caption and script were softened, because this session could not record the presenter (see section 3).

Item 1, tests: `scripts/tally.py --write` and `scripts/build_log.py --write` run as the repo prescribes (the README count now reads 115 commits at the time of writing); no test skipped or deselected.
The sweep tests that fail in a fresh worktree trace to `tests/fixtures/site_sweep/page/data/` being swallowed by the root `data/` gitignore rule — the fixture exists only in the main checkout; copied locally (still gitignored) they pass.

## 2. What was checked

- `uv run --extra site pytest -q`: 1079 passed, 19 skipped, 1 warning.
- `uv run ruff check .`: all checks passed.
- `scripts/tally.py --check` and `scripts/build_log.py --check`: both pass.
- `scripts/site_sweep.py`: all seven checks pass on the rebuilt bundle and edited page.
- Replay, locally: 3 of 3 lines identical, sha256 `d991b59e6768a1f6b77bdd0fd0c4c6fb45afbe9d837bdfc9abab0fbfaaff7010`; the shipped-set replay on the box reproduced the same hash (3 of 3).
- Live site after deploy: `/api/health` reports commit `819d039`; `data/index.json`, `data/racing.json`, `data/shift.json`, `app.js`, two per-clip JSONs, the film MP4, and the GitHub repo all return 200; a headless-Chromium render shows the headline numbers, the hero deciding number, and both traces populated (JS-filled, so checked rendered, not raw).
- Film: ffprobe of the web copy above; frames extracted and viewed for the hero, compile, shift, replay-capture, and closing scenes.

## 3. Not done, and why

- The closing narration was not re-recorded: no voice take or cue file exists in the repo, and synthesising the presenter's voice was not acceptable. SCRIPT.md, the on-screen caption, and captions-v2.srt carry the softened line.
- The on-box graded-set replay is 25 of 26: `reversing_no_spotter_cctv_33` rebuilds to a different record on the Linux box (rebuilt set `f0e8aba0a4399907786a178794c416bb9992f5a285c809aab517081ac7c9b4b9` vs shipped `43afe3f7542eb0807723dea560ecfde31ab318ad54c059868e93394e20c39701`), with current code and current record roots, so `/api/graded26` writes nothing and the page hides that box. The mismatch predates this pass; its root cause is still open.
- The sweep fixture gap above: un-ignoring `tests/fixtures/site_sweep/page/data/` (or moving the fixture) is a repo-policy change left to the owner.
- The film web copy sits in the box's `www/` outside the sweep; any `deploy_site.py` run republishes `www/` and removes it, so it must be re-uploaded after a deploy (done after the last one; verified 200).
- The submission form still points where it pointed: changing it is the owner's step. The new cut is at https://metahackathon.pitbot.gg/faultline-film-web.mp4 with `demo/captions-v2.srt` as captions.

## 4. Commits

On `task/faultline-final-submission-improvements` (worktree beside the project; not pushed, not merged):

| Commit | What |
|---|---|
| `0d5539b` | Judge's path, hero case, Meta traces, shift label clarity (9 files) |
| `11e12cf` | Tally and build log for that change |
| `2331cdf`, `819d039` | Ruff line-length fixes in the stored-ruling test |

Landing is the owner's `/glitch-close`; the push happens on his word, as STATE.md's handoff says.
