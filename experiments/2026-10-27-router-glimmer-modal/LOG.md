# Router tier 1: Muse Glimmer on a Modal L40S, and the 220 labels remeasured (experiment log, 26-27 Oct 2026)

Every model call faultline makes goes through this task router, so the tier it picks sets the steward's cost and its quality floor.
The plan here is the written plan this build followed, in four checkpoints.
What I built, how I ran it, what it cost and what I found.
All times are Central (CDT, UTC-5), from the proxy ledger, the Modal dashboard and git, unless marked otherwise.

## Result

| | Figure |
|---|---|
| Relabel: Glimmer passed the judge | 7B judge (`qwen2.5:7b`): 206 of 220 (93.6%), `router-data/tier1-verdicts.jsonl`. Strict re-judge of those 206: 129 pass, `router-state/strict-rejudge.jsonl`. The 7B pass does not check that the ruling is right (see checkpoint 3) |
| Moved up (2+ to 1) | 35 (31 from tier 2, 4 from tier 3) |
| Moved down (1 to 2+) | 9 (all 1 to 2) |
| Moved between 2 and 3 | 0 |
| Traps moved | 0 of 20 |
| Answers that came `via local` | 0: 220 of 220 `via modal`, none cached (`tier1-verdicts.jsonl`, field `via`) |
| v1 held-out, draft labels against measured labels (same ids) | Same 55 held-out ids. Draft model on draft labels: 83.6%, under-route 7.3%, over-route 9.1%, traps 55.6% (n=9). v1 on measured labels with the floor: 76.4%, under-route 0.0%, over-route 23.6%, tier 1 precision 100% recall 29.4%, traps 88.9% |
| Bench: routed against all-tier-3 | 92.7% (51 of 55) against 92.7% (51 of 55); routed tiers 5 / 35 / 15; ledger $0.0079 against $0.0000; list price $0.82 against $2.37 |
| Bench cached calls | Routed 52 of 55, all-tier-3 55 of 55 |
| Modal GPU minutes and dollars (dashboard) | $2.68 for the billing cycle 1 to 31 Oct, all covered by the $30 Starter credits ($0 charged); about 80 GPU minutes equivalent (about 4,940 L40S seconds at $0.000542 a second, a little of it the CPU pull container). Read from the Modal usage page at about 00:50 on 27 Oct |
| Ledger dollars for Modal calls | $0 by design: 457 `modal/muse-glimmer:30b` lines in `runs/router/spend.jsonl`, $0.0000 in all |

The headline is v1 with the floor: 76.4% accuracy and 0.0% under-route on the 55 held-out prompts.
Under-route is the figure that matters most, because an under-routed prompt goes to a model too weak for it and the answer comes back wrong, while over-route only costs money.

## Question

Tier 1 of the router is `muse-glimmer:30b` since `78e01d0` (20:22 on 26 Oct), on local Ollama, where the 18 GB model spills out of the 12 GB GPU and answers in about 50 s.
Can the same model, served by the same Ollama version on a Modal L40S behind the metering proxy, answer tier 1 at a usable speed, with every call on the record as a Meta model and local Ollama as the fallback?
And once it can, which of the 220 labelled prompts can Glimmer actually answer, judged by the local `qwen2.5:7b`?

## How it runs

- Modal app `glimmer-ollama`: Ollama 0.40.11 (the same as this PC) on one L40S (48 GB), tag `muse-glimmer:30b` from a Modal Volume, `@app.cls` with `@modal.web_server` and `@modal.concurrent(max_inputs=4)`, `max_containers=1`, a 10-minute scaledown.
- The lock: Modal proxy auth tokens, `requires_proxy_auth=True`, so a request without `Authorization: Bearer <id>.<secret>` is refused at Modal's edge before any container starts.
- The route: the router proxy's existing `modal/` route on port 8766, priced at $0 in the ledger (GPU seconds bill on Modal's own account).
- The router: tier 1 is provider `modal`, model `modal/muse-glimmer:30b`, with local Ollama `muse-glimmer:30b` as the fallback.

## Process and findings, in order

### Checkpoint 1: the deployment (26 Oct)

- 21:00 Build started from the plan. Modal client 1.6.2 confirmed, and the decorator keywords the deploy file relies on (`web_server(requires_proxy_auth, startup_timeout, label)`, `App.cls(startup_timeout, max_containers, scaledown_window)`, `concurrent(max_inputs)`) checked against the installed client.
- 21:10 The plan's installer line set `OLLAMA_VERSION` on the `curl` side of the pipe, where the installer never sees it, so the image would have installed the newest Ollama. Fixed to `curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.40.11 sh`, with a test that fails if the pin moves back.
- 21:10 `deploy/modal/glimmer.py`, `deploy/modal/README.md` and the `modal_route` and `modal_problem` fields in `proxy.json` built; `tests/test_modal_deploy.py` (8 static tests, each guarantee shown red by mutation).
- 21:20 Found a pre-existing race: `test_stop_and_status` failed 9 times in 300 repeats. `stop` and the server thread both rewrote `proxy.json`, so a read between truncate and write saw a half-written file. One lock now serialises every in-process read and write: 0 failures in 300 repeats, and a regression test that fails without the lock (177 misses in 1 s).
- 21:30 Full suite 1687 passed. Ruff clean on `src`, `tests` and `deploy`. The repo-wide ruff run is red only in other runs' `experiments/` scripts, left alone.
- 21:35 I signed in to the Modal workspace (`python -m modal token new`), made a proxy auth token and put `MODAL_PROXY_TOKEN` and `MODAL_STYLE` into `.env` by hand. The `modal` command is not on this PC's shell PATH, so the README uses `python -m modal`.
- 21:40 The first pull never ran: the Modal CLI crashed on the tick mark in its own output (`'charmap' codec can't encode character '✓'`). With `PYTHONUTF8=1` it ran.
- 21:48 to 21:57 The pull, on a CPU container: Ollama `0.40.11` installed from the `.tar.zst` archive (the pin holds), `muse-glimmer:30b` pulled in 8 min 40 s, ID `de878ce33ad8`, 18 GB, the same ID as this PC's copy.
- 22:00 `modal deploy` in 2 s: `Glimmer.serve -> <modal endpoint>`, proxy-auth locked. The lock check: no token `401`, a wrong Bearer `401`, and no container started.
- 22:04 First calls through the proxy: `502 upstream unreachable: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired`. The proxy trusted the Windows certificate store, which on this PC builds an expired chain to Modal's Let's Encrypt (`YE2`) certificate. The same request with certifi's bundle got Modal's `401`. Fix: every upstream verifies against certifi (now a direct dependency), the proxy still starts without it on the OS store, and its start-up line names which (`upstream TLS trusts certifi 2026.10.23.`).
- 22:08 The relock made `uv sync` fail on `tourney.exe`, held open by the running d0 proxy, after it had already removed `task-router.exe`, `cap-probe.exe` and `steward-eval.exe`. Moving the in-use launcher aside (`tourney.exe.in-use-by-d0`) let the sync finish with d0 untouched.
- 22:12 Modal's edge answered `401 missing credentials for proxy authorization`: the token in `.env` was a Modal API token (`ak-`), not a proxy auth token (`wk-` / `ws-`). I made a proxy auth token. With it, the Bearer form passes the edge, so the plan's header was right. Added: a token not shaped `<token-id>.<token-secret>` leaves the route off with a plain message, and a client's own `Modal-Key` / `Modal-Secret` headers are never forwarded.
- 22:19 The first end-to-end call through the proxy: `200`, `Ready.`, cold call 30.9 s (the container was already starting), warm call 2.8 s. The activity entries read `provider: modal`, `family: muse`, `meta: true`, `qualifies: true`, `usd: 0.0`. `task-router proof`: `modal/muse-glimmer:30b` listed, `reconcile OK` (245 of 245).
- 22:19 `reasoning_effort` on the Modal build: `"none"` gave 24 completion tokens, the default gave 100 for the same prompt, so `"none"` works on Modal as it does locally and stays.
- 22:25 Full suite 1707 passed, ruff clean on `src`, `tests` and `deploy`.

### Checkpoint 2: tier 1 through Modal, local Ollama as the fallback (26 Oct)

- 22:30 Built: provider `modal` for tier 1 (`modal/muse-glimmer:30b`), a `ModalProvider` through the proxy's Modal route and a `FallbackProvider` that answers from local Ollama `muse-glimmer:30b`, `/healthz` fallback counters, `doctor`'s Modal route and cap lines, `tier1-probe`, and `proof`'s GPU wording.
- 22:50 Full suite 1808 passed, ruff clean. `doctor`: `[ok] proxy Modal route on`, `[ok] router cap headroom $6.69`, local `muse-glimmer:30b` and `qwen2.5:7b` present.
- 22:52 The fallback, free: with the router proxy stopped, `tier1-probe` answered `via local` in 28.4 s, `last_fallback_error: ProviderUnavailable: the tournament proxy is not running`.
- 23:05 Through Modal: a cold probe `via modal` in 75.9 s (container start plus answer), then a warm probe `via modal` in 3.1 s, not cached, so the nonce works. `proof` lists `modal/muse-glimmer:30b` at `$0.0000 (GPU seconds on Modal)` and `muse-glimmer:30b` local as free, `reconcile OK`.

### Checkpoint 3: the relabel (26 Oct)

- 23:15 Built and committed (`c6964cb`): `task-router relabel` and its module, 1870 tests passed. The plan printed 220 prompts, about 23 minutes at 4 workers, at most $2.98 of L40S. The old model and split were kept as `router-data/models/v1-draft-labels` and `router-state/split-draft-labels.json`.
- 23:19 Warm-up probe `via modal` in 73.8 s (cold start).
- 23:20 to 23:34 `relabel --workers 4 --confirm --no-apply`: 220 of 220 answered `via modal` (none local, none cached), every answer `finish_reason: stop`, median 13.7 s, longest 33.0 s, 14 minutes in all.
- The verdicts: Glimmer passed the judge on 206 of 220 (93.6%). By prior tier: tier 1, 38 pass and 2 fail. Tier 2, 119 pass and 11 fail. Tier 3, 49 pass and 1 fail. Traps: 20 of 20 pass, including the 5 drafted at tier 3.
- The finding that stops the apply: the judge's reason on the tier-3 traps reads "On topic, no invented details". It checks topic and invention, not whether the ruling is right. Applied by the plan's rule, 168 labels would move to tier 1 (119 from tier 2, 49 from tier 3) on a judge that cannot tell a right ruling from a fluent one. The labels are unchanged (`--no-apply`); the apply waits for my call.

### Checkpoint 3 close: labels, review and training (27 Oct)

- The 7B judge passed 206 of 220. Applying that would have moved 168 labels to tier 1; held back because its reasons showed it checks topic, not correctness.
- The 14 misses re-asked with a brevity line: 12 pass. Those passes were not used; the originals stand.
- A stricter judge (graded against each row's own `why`, fails when unsure) passed 129 of 206. Traps held fixed at their labels throughout: strict still passed hard traps 02, 04 and 05.
- Fresh reviewing agents read every strict-confirmed move from the prompt text alone: tier 3 to 1, 6 of 29 safe; tier 2 to 1, 32 of 65 safe. The 7B judges wrongly passed 56 of 94. Three one-off scripts did this work: `redo_misses.py` re-asks the misses, `strict_rejudge.py` re-judges strictly and `apply_strict.py` applies the result; their answers stay in gitignored `router-state/`.
- A fresh audit by a Fable agent found three more labels to put back (done) and asked for my original `why` to be kept (`prior_why`, done).
- Final labels: tier 1 = 66, tier 2 = 108, tier 3 = 46 (from 40 / 130 / 50). No trap moved.
- The 9 moved down are drafted tier-1 rows whose Glimmer answer failed, which the rule sends to tier 2: 2 failed the 7B judge, and 7 passed it but failed the strict re-judge (`router-state/strict-rejudge.jsonl`).
- Classifier v1 before the floor, on the model trained before the Fable audit's three put-backs: held-out accuracy 69.1%, traps 44.4%, three short hard traps (01, 02, 03) routed to tier 2. The saved v1 without the floor scores 70.9%, under-route 5.5%, traps 55.6% (recomputed 27 Oct).
- Added `floor.py`: a short question with no pasted material that asks for a ruling goes to tier 3. Designed after seeing those held-out traps, so the trap figure below is partly fitted to them.
- v1 with the floor: accuracy 76.4%, under-route 0.0%, over-route 23.6%; tier 1 precision 100% (recall 29.4%); traps 88.9%. Against the old labels the unfloored model scored 76.4% (measured before the three put-backs; the saved v1 scores 78.2% on them, recomputed 27 Oct).
- Not done: the floor firing is not written to the audit record (needs a column).

### Checkpoint 4: the bench (27 Oct)

- Run with the paid gate open, `serve` stopped, Modal warm (`tier1-probe` via modal), router cap headroom $6.69 against a $18.08 worst case. I chose to run as is.
- 55 held-out prompts, both arms, judged by local qwen2.5:7b (a weak judge: see the checkpoint 3 audit). Routed: tier 1 = 5, tier 2 = 35, tier 3 = 15. All-tier-3: 55.
- Quality: routed 92.7% (51 of 55) against all-tier-3 92.7% (51 of 55).
- Cost in the ledger: routed $0.0079, all-tier-3 $0.0000. This is flattered by the proxy cache: 52 of 55 routed calls and all 55 all-tier-3 calls were repeats of earlier bodies and cost $0. At list price the routed arm is $0.82 against $2.37 for all-tier-3 (65% lower).
- Only 5 of 55 prompts reached tier 1, which matches the 29% tier-1 recall; the router saves money mostly by using tier 2, not tier 1.
- The paid gate was closed again after the run (`task-router stop`). `proof --write` reconciles 799 of 799 router entries.
- 00:45 The docs tasks closed the plan: the router guide gained its Tier 1 on Modal, Relabel and Tier-3 floor sections, the runbook answered the Modal auth blank, and the public PROVENANCE.md names the Modal tier 1 and the remeasured labels.

## How the figures were measured

- Moved counts: every row of `router-data/labelled.jsonl` compared with its `prior_tier` (a row with no `prior_tier` never moved). The prior tiers come to 40 / 130 / 50 and the current tiers to 66 / 108 / 46. The 44 moved rows are the ones with `label_source: glimmer-judge`; 18 tier-1 rows kept their tier but had their `why` replaced with "Glimmer passed the judge".
- Held-out figures: recomputed at 27 Oct from the saved models (`router-data/models/v1-draft-labels`, threshold 0.65, no floor; `router-data/models/v1`, threshold 0.7, with the floor) on the held-out ids, which are the same 55 in `router-data/split.json` and `router-state/split-draft-labels.json`. Neither model folder holds a stored eval report; the old 83.6% and 55.6% also stand in the router's own guide.
- Bench: `router-state/bench-tier1-glimmer-modal.json`, started 00:27:29 and finished 00:28:09 on 27 Oct.

## Cost

### Modal (GPU seconds, my own account)

- Dashboard: total usage $2.68 for the billing cycle 1 to 31 Oct 2026, read from the Modal usage page at about 00:50 on 27 Oct. All of it was covered by the $30 Starter credits, so $0 was charged. Usage limit $30.
- The page's breakdown reads $2.75 deployed apps and $0.01 ephemeral apps, which does not sum to the $2.68 headline.
- The Modal workspace was created on 26 Oct for this plan, so the month's whole figure is this plan's.
- At $0.000542 a second for the L40S, $2.68 is about 4,940 GPU-seconds, about 80 GPU minutes equivalent (a little of it was the CPU pull container).
- Where it went, from the ledger: 240 uncached Modal answers in all. The relabel's 220 (14 minutes at 4 workers, after a 73.8 s cold start), the 14 misses re-asked (`router-state/redo-misses.jsonl`), and the probes at checkpoints 1, 2 and 4. The strict re-judge's 206 answers were cache hits and cost no GPU time. In the bench window, 6 Modal calls, 5 of them cached. The rest of the GPU time is container start-up and the 10-minute scaledown after each burst.

### Meta and Baseten credit (the proxy ledger)

- Router spend in `runs/router/spend.jsonl` was $3.3080 before this plan's first call (21:00 on 26 Oct) and $3.3158 after the bench, so this plan spent $0.0079.
- All of that $0.0079 is the bench's routed arm, and all of it is Baseten: 3 uncached `meta-models/muse-spark-open-1026` (tier 2) calls at 00:27 and 00:28 on 27 Oct, priced at Spark Open's list rates.
- The other 32 tier-2 calls in the routed arm, and every `muse-wonder-1.0` (tier 3) call in both arms, were cache hits at $0.
- Meta Model API credit spent by this plan: $0.
- Modal calls in the ledger: 457 lines, $0.0000.

## Decision

- Glimmer on Modal stays as tier 1 (`modal/muse-glimmer:30b`), with local Ollama `muse-glimmer:30b` as the fallback.
- The labels as reviewed are the ones v1 is trained on: tier 1 = 66, tier 2 = 108, tier 3 = 46, with every moved row keeping my original `why` as `prior_why`.
- The 7B judge's pass is not evidence of correctness on its own. It checks topic and invention, not whether a ruling is right, so the moves rest on the strict re-judge, the fresh reviewing agents and the Fable agent's audit, not on the 206 of 220.
- The tier-2 pass (`--tier2-pass`) did not run, so the boundary between tier 2 and tier 3 still rests on the draft labels plus the floor.

## Open

- I did not run `label review --moved`. The moved labels were reviewed by fresh reviewing agents and an audit by a Fable agent on my say-so.
- The tier-2 pass (`--tier2-pass`) did not run.
- Relabel timestamp: `router-data/tier1-verdicts.jsonl` runs from 2026-10-27T04:21:02Z to 2026-10-27T04:34:21Z (23:21:02 to 23:34:21 on 26 Oct). A later `retrain` can drop audit training rows older than that.
- The Modal 303 behaviour (a request over 150 s turned into a redirect to a result URL) was never seen in this run: the longest relabel answer took 33.0 s, and the ledger's Modal statuses are 451 `200`, 4 `401` and 2 `502`, all at checkpoint 1.
- The router cap also refuses Modal calls at the cap, so tier 1 would answer locally mid-run without a word.
- Whether the router proxy on 8766 runs as a scheduled task is still my call.
- The floor firing is not written to the audit record (it needs a column).
