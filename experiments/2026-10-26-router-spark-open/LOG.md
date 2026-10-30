# Router tier 2: Muse Spark Open against Muse Spark 1.3, experiment log (26 Oct 2026)

Every model call faultline makes goes through this task router, so its choice of tier sets the steward's cost and its quality floor.

What I tested, how I ran it, what it cost and what I found.
All times are Central (CDT, UTC-5) on Monday 26 Oct 2026, from the proxy ledger and git, unless marked otherwise.

## Result

| | Run A: tier 2 = `muse-spark-1.3` | Run B: tier 2 = `meta-models/muse-spark-open-1026` |
|---|---|---|
| Routed arm passed the judge | 50 of 55 (90.9%) | 49 of 55 (89.1%) |
| All-tier-3 arm passed (same in both) | 51 of 55 (92.7%) | 51 of 55 (92.7%) |
| Tier 2 calls | 34 | 34 |
| Tier 2 calls at the 8,192 ceiling | none seen | 0 of 34 |
| Tier 2 cost (routed arm, less tier 3) | about $0.28 (Meta credit) | $0.26 (Baseten credit) |
| Wall time | 28 minutes | 4.5 minutes (tier 3 answered from cache) |

Spark Open passed one prompt fewer than Spark 1.3, at about the same cost per call.
One prompt in 55 is inside the noise of a local 7B judge.
The routed router stays within two to four points of sending everything to Wonder, at a third of the cost or less.

## Question

I received a $100 Baseten API key (2M tokens a minute) for Muse Spark Open, sent with the hackathon emails.
Baseten offers no spend cap on its site, so the router's own $10 cap in code is the only cap.
I saved the key into the `.env` at 18:05 (the file's modified time).

Can Muse Spark Open replace `muse-spark-1.3` as the router's tier 2 without losing answer quality?
If it can, tier 2 spends the Baseten credit instead of the $150 Meta credit.

Tier 3 (`muse-wonder-1.0`) stays as it is: it is the large model the router escalates to, and Spark Open is a Spark-class model.

## Public benchmarks first

When: 26 Oct, before the first paid call at 18:08 (no exact time kept).

| Measure | Spark 1.3 | Spark Open |
|---|---|---|
| Artificial Analysis Intelligence Index (independent) | 48 (Max) | 39 (Xhigh) |
| Terminal-Bench 2.1, DeepSWE 1.1 (vendor and aggregator) | about 7 to 9 points higher | lower |
| MCP-Atlas, JobBench (vendor) | lower | Spark Open leads |
| Tokens to finish the whole index | 170M | 110M |
| Price per 1M tokens | $1.25 in, $4.25 out (Meta) | $1.25 in, $4.25 out (Baseten) |

Sources: artificialanalysis.ai/models/muse-spark-open, artificialanalysis.ai/models/muse-spark-1-3, orcarouter.ai/blog/muse-spark-open-vs-muse-spark-1-3, dev.meta.ai/models/muse-spark-open, baseten.co/library/muse-spark-open.
Baseten's page gives the size as 816B-A42B (a mixture-of-experts model) and no benchmarks.

None of these tests measure my job, ruling on racing incidents.
A weaker tier 2 also sends more prompts up to Wonder, which costs $20 per 1M output tokens.
So I measure on my own held-out set instead of trusting the general scores.

## How it runs (technical)

- Every paid call goes through the metering proxy, run `router`, on 127.0.0.1:8766, under the `tourney-router` token.
  Port 8765 belongs to the `d0` probe proxy, so the router proxy moved to 8766.
- Each call is a line in `runs/router/spend.jsonl` (the ledger), with a UTC timestamp.
- Router cap: `TOURNEY_ROUTER_CAP_USD`, not set in `.env`, so the code default of $10 applies.
- The Baseten key sits in `.env` as `BASETEN_API_KEY`, which I put there.
  The proxy sends any `meta-models/...` model to `https://inference.baseten.co/v1` with that key.
- The bench: `task-router bench --set heldout --confirm` (described in the "Bench" section of the router's guide).
  It replays the 55 frozen held-out prompts twice: once through the router as it routes live, once forced to tier 3.
  The local judge, `qwen2.5:7b` on Ollama, grades every answer pass or fail, at $0.
  Tier 1 is local `llama3.2:1b` in both runs; it changed to Muse Glimmer later that evening, at 20:22 (commit `78e01d0`).
  The router model (v1) decides the tier per prompt, so the same 34 prompts reach tier 2 in both runs.
- The comparison is two bench runs that differ only in the tier 2 model in `router.config.json`.
  Run B's forced tier-3 arm repeats run A's calls, so the proxy cache answers them at $0, and its 12 routed tier-3 calls too.
- Results: `router-state/bench-tier2-spark-1.3.json` and `router-state/bench-tier2-spark-open-1026.json` (git-ignored).
- `scripts/len_check.py`, a short length-check script, sends one held-out prompt to named models and prints finish reason, answer length and token use.

## Process and findings, in order

### 1. The key opens only the hackathon build of Spark Open

When: 18:08 to 18:10.

- 18:08:32: the first proxy call to `meta-models/muse-spark-open` returned 403: `please check the api-key you provided`.
- The key's `.env` line was well formed (45 characters, no quotes or spaces), checked without printing it.
- The key worked on Baseten's free `GET /v1/models`, with both `Bearer` and `Api-Key` schemes.
- That list holds both `meta-models/muse-spark-open` and `meta-models/muse-spark-open-1026`.
- Between 18:08 and 18:10 (not in the ledger, so no exact time): one tiny direct chat call to each.
  The plain slug answered 403, and `meta-models/muse-spark-open-1026` answered 200.
  These two direct calls skipped the proxy, so they are not in the ledger (well under a cent).
- Finding: use `meta-models/muse-spark-open-1026`.
  It has no public price, so `prices.json` gives it Spark Open's public rates.

### 2. Every paid tier returned an empty answer at the router's 256-token limit

When: 18:08:36 to 18:10:36 (ledger calls 7 to 19).

One held-out prompt, sent with `scripts/len_check.py` at `max_tokens` 256:

| Setting | Spark Open 1026 | Spark 1.3 | Wonder |
|---|---|---|---|
| default effort | 403 (old slug) | not run | empty, 254 of 256 tokens reasoning |
| `reasoning_effort: low` | empty, 253 reasoning | empty, 254 reasoning | empty, 254 reasoning |
| `reasoning_effort: none` | empty, 253 reasoning | 400: `none` not supported | 400: `none` not supported |
| `reasoning_effort: minimal` | empty, 253 reasoning | 593 characters, cut off (110 reasoning) | 485 characters, cut off (150 reasoning) |
| default effort, `max_tokens` 2048 | 725 tokens, `stop` | 993 tokens, `stop` | 883 tokens, `stop` |

- Meta's API accepts `minimal`, `low`, `medium`, `high`, `xhigh` and `max` for Spark 1.3 and Wonder.
- Between 18:10 and 18:23: Baseten's reasoning docs (docs.baseten.co/inference/model-apis/reasoning, a link I supplied) confirm Spark Open always reasons.
  Its values are `low`, `medium`, `high` and `xhigh` (the default), and `none` and `minimal` run at `low`.
- Both APIs count reasoning inside `max_tokens`, and the answer comes back in `content`, the reasoning in `reasoning_content`.
- Finding: the router gave every paid call 256 tokens, so every paid answer came back empty, live and in the bench.
  This was a real router bug, not only a bench problem.
- Decision: keep each model at its default effort, because the public scores used `xhigh` for Spark Open.

### 3. Fix one: 2,048 tokens a call (commit `635aed2`, 18:23)

- The proxy provider adds `REASONING_HEADROOM_TOKENS` on top of the caller's `max_tokens`, which stays the answer budget.
- The first value was 1,792, so 256 became 2,048.
- The bench's cost estimate counts the headroom, and a test pins the request body.
- First bench attempt, 18:24:12 to 18:27:20, stopped by hand ($0.30, ledger calls 20 to 35):
  6 of 16 calls used all 2,048 tokens (4 of 9 Wonder, 2 of 7 Spark 1.3).
  The `e808b0d` commit message says 5 of 15, the count at that moment; one more call landed before the stop.
- Finding: 2,048 still cut off over a third of answers.
  A cut-off scores as a fail and favours the model that reasons less, so the comparison would be unfair.

### 4. Fix two: 8,192 tokens and a 300 s timeout (commit `e808b0d`, 18:34)

- The headroom went to 7,936, so 256 becomes 8,192.
- The router's request timeout went from 120 s to 300 s, because that much reasoning can pass two minutes.
- The proxy's own upstream timeout is 600 s, so it stays.
- 18:35: a parallel run committed the same `muse-spark-open-1026` price row (`4b7e0cf`), so `prices.json` held it twice with equal values.
  The duplicate is removed in the commit that adds this log.

### 5. Run A: tier 2 = `muse-spark-1.3`

When: 18:34:50 to 19:02:57.

`bench: routed $0.7167 vs all-tier-3 $1.9363 (measured), quality 90.9% vs 92.7%`

| | Routed | All tier 3 |
|---|---|---|
| Answered | 55 of 55 | 55 of 55 |
| By tier | tier 1: 9, tier 2: 34, tier 3: 12 | tier 3: 55 |
| Passed the judge | 50 (90.9%) | 51 (92.7%) |
| Cost | $0.7167 | $1.9363 (12 calls cached, list price $0.4375) |
| Output tokens | 86,963 | 117,876 |

- Early in the run, 1 of 18 calls hit 8,192 (Wonder), and none of Spark 1.3's.

### 6. Run B: tier 2 = `meta-models/muse-spark-open-1026`

When: 19:03:17 to 19:07:53.
`router.config.json` tier 2 was changed on local main for this run only, and put back to `muse-spark-1.3` at 19:08.

`bench: routed $0.2617 vs all-tier-3 $0.0000 (measured), quality 89.1% vs 92.7%`

| | Routed | All tier 3 |
|---|---|---|
| Answered | 55 of 55 | 55 of 55 |
| By tier | tier 1: 9, tier 2: 34, tier 3: 12 | tier 3: 55 |
| Passed the judge | 49 (89.1%) | 51 (92.7%) |
| Cost | $0.2617 (12 tier-3 calls cached, list price $0.4375) | $0.0000 (55 cached, list price $2.3738) |
| Output tokens | 81,474 | 117,876 |

- Spark Open's 34 calls averaged 1,755 output tokens, and none hit the 8,192 ceiling.
- The all-tier-3 arm is the same cached answers as run A, so its 92.7% matches by design.

## Cost

| Step | When | Router ledger |
|---|---|---|
| Checking calls (steps 1 and 2) | 18:08 to 18:10 | $0.09 |
| First bench attempt, stopped (step 3) | 18:24 to 18:27 | $0.30 |
| Run A | 18:34 to 19:02 | $2.65 |
| Run B | 19:03 to 19:07 | $0.26 |
| Total | | $3.31 of the $10 cap |

The first estimate was $2 to $3 for both runs, and the total came to $3.31.

## Decision

My call, 26 Oct about 19:15 (chat message, no exact time kept): tier 2 switches to `meta-models/muse-spark-open-1026`.
My reason: Spark Open scored close to Spark 1.3, and the steward should use more of Meta's open-weights models.

## Open

- The judge is a local 7B model, so treat small pass-rate gaps (one or two prompts) as noise.
- All 220 label rows carry `label_source: brock` since the 26 Oct 12:29 commit `b9c21f9`, with no tier changed from the draft.
  The labels also do not affect the judge: they train the routing model (which tier a prompt goes to), while the judge grades each answer on its own.
- Which prompt flipped between runs A and B is not yet read from `router-state/bench.db`.
