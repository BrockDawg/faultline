# Capability probe, Day 0: run log (26 Oct 2026)

What the capability probe measured on Meta's models, how the run went, what broke, what it cost and what went into the brief.
Day 0 is kickoff day (26 Oct): the probe runner scores each candidate steward feature on Meta's models, and the best results are written into the design brief the build works from.
A slot is a named model in the probe's config, and the d0 proxy is the metering proxy run for Day 0, which holds the API key and caps spend.
All times are Central (CDT, UTC-5) on Monday 26 Oct 2026, from `probe-state/results.jsonl` and git, unless marked otherwise.
The probe itself is described in the probe runner's own guide.

## Result

All 29 probes that can run have run: 15 worked, 14 worked badly.
`reach-05` cannot run, because Meta's Model API serves no Glimmer model (Glimmer runs locally only).

`cap-probe rank` (about 19:55):

| # | Score | Feature | Outcomes |
|---|---|---|---|
| 1 | 0.75 | Local uncertainty signal for the router | worked, worked, worked badly |
| 2 | 0.63 | Contact detection from SAM masks | worked, badly, worked, badly |
| 3 | 0.59 | Calibrated ruling confidence | worked, badly |
| 4 | 0.48 | Precedent and consistency auditor | badly, worked, badly |
| 5 to 9 | 0.21 to 0.25 | Debris flag, occlusion-robust tracking, track limits from masks, contact from chat-model vision, spoken emphasis | worked badly |

Brief: two lines written into `brief/BRIEF.md` under "Measured on Day 0" (commit `9e65b7f`, 19:55), chosen by me.
Calibrated confidence was left out (see spark-05 below).

## Every probe, in run order

| Time (CDT) | Probe | Outcome | Ledger $ | What it showed |
|---|---|---|---|---|
| 13:45 | reach-06 | worked | 0 | `muse-glimmer:30b` is listed on local Ollama |
| 14:28 | local-01 | worked | 0 | Glimmer returns logprobs (165 tokens, thinking off) |
| 14:56 | local-02 | worked | 0 | 10 rulings x 5 samples, mean agreement 0.98, none below 0.6 |
| 14:56 | local-03 | worked badly | 0 | no low-agreement ruling, so agreement gives the router no signal on Glimmer |
| 15:31 | reach-01 to 04 | worked | 0.10 | `sam-3.1`, `muse-spark-1.3`, `muse-voice-transcribe-1.0`, `muse-wonder-1.0` are listed |
| 15:31 | reach-05 | not run | 0 | no Glimmer on Meta's API |
| 15:33 | spark-01 | worked badly | 0.006 | `json_schema` refused (400), `json_object` reply did not match the schema |
| 15:33 | spark-02 | worked badly | 0 | `logprobs` refused: "not supported with reasoning" |
| 15:33 | spark-03 | worked | 0.003 | image input accepted |
| 15:33 | spark-04 | worked badly | 0 | `n=3` refused: "`n` must be 1" |
| 15:58 to 15:59 | sam-01, 02 | worked | 0 (unmetered) | masks returned on one car and on a pack |
| 15:59 | sam-03 | worked badly | 0 (unmetered) | car identity not held across 6 frames |
| 15:59 | sam-04 | worked | 0 (unmetered) | contact at frame 0 (overlap 20 px, closing speed -24.9 px a frame) |
| 15:59 | sam-05 | worked badly | 0 (unmetered) | false contact at frame 1 (overlap 9 px) |
| 15:59 | sam-06, 07, 08 | worked badly | 0 (unmetered) | no masks on placeholder frames (track edge, occlusion, debris) |
| 19:36 | spark-05 | worked | 0.062 | Brier 0.2489 over 10 rulings |
| 19:37 | spark-vision-contact | worked badly | 0.035 | no contact found on a known-contact item |
| 19:38 | wonder-01 | worked | 0.141 | accepts chat, answers with text, repeat is a cache hit |
| 19:38 | cross-01 | worked | 0.002 | an identical repeat is a proxy cache hit at $0 |
| 19:50 | spark-06 | worked badly | 0.011 | nearest past ruling picked had a different verdict |
| 19:50 | audit-01 | worked badly | 0.016 | the planted inconsistency was not named |
| 19:50 | audit-02 | worked | 0.010 | no false alarm over 12 rulings |
| 19:50 | voice-01 | worked badly | 0.10 (fallback) | 32 words, 2 timed turns, no word timestamps |
| 19:50 | voice-02 | worked badly | 0.10 (fallback) | no emphasis word in the clip |

The SAM probes ran before the proxy priced SAM by images and frames (`acf2b30`, 17:23), so their $0 is not a real cost.

## Process, in order

### 1. Local slot on Glimmer (13:45 to 14:56)

- `672d7d8` (13:45): the local slot runs `muse-glimmer:30b` instead of `llama3.2:1b`, with thinking off in the client.
- The first local-02 run timed out: local-01 and local-02 built their own requests and skipped the client, so thinking stayed on.
- `320be2c` (14:28): both probes send through the client; a test checks the request on the wire.
- With thinking off, local-02 took about 40 s and 205 to 261 tokens a call.

### 2. Meta slots named, proxy kept running (14:01 onwards)

- `c637559` (14:01): slots named `muse-spark-1.3`, `sam-3.1`, `muse-voice-transcribe-1.0`, `muse-wonder-1.0`; the glimmer Meta slot stays null.
- The `d0` proxy runs from the scheduled task "ai-steward d0 proxy" (`runs/d0/proxy-loop.ps1`), which restarts it 60 s after any exit, until 5 Nov.

### 3. Reach, Spark and SAM probes (15:31 to 15:59, another run)

- `42cf04a` (15:30) points the contact probes at real Day 0 dev clips, and `cced00d` (15:57) moves the SAM probes to the Responses API that serves `sam-3.1`.

### 4. Cap raised to $20, the 9 remaining probes (19:35 to 19:38)

- The 9 probes had status `not_configured` from runs before the slots were named.
- `tourney-probe` had spent $6.94 of its $10 cap, shared with the steward-limits run, and the 9 probes' budgets added up to $3.30.
- `cap-probe` read its own cap as the $5 default, so it would have refused to run.
- I said yes to $20 (about 19:33): `$env:TOURNEY_PROBE_CAP_USD = '20'` in `proxy-loop.ps1`, and the same cap in the local environment file so `cap-probe` reads the same.
- The proxy task was ended and run again at 19:35, a gap of about a second for the other run.
- Results: spark-05, spark-vision-contact, wonder-01 and cross-01 ran; five broke.

### 5. Two faults found and fixed (`a3724d8`, 19:49)

- **Voice:** voice-01 and voice-02 posted to `/v1/audio/transcriptions` and got HTTP 502.
  The proxy log showed the steward-limits run getting 200 from `/v1/asr/transcribe`.
  Its script showed the shape: a multipart `request` part with JSON `{"mode", "model", "audioEncoding": "WAV"}` and an `audio` part with a 16-bit mono WAV.
  `DIARIZATION` returns `transcript` and `turns` (`startMs`, `endMs`, `speaker`); there are no word timestamps.
  The probes now use that endpoint; voice-01 scores turn-level timing as worked badly, and voice-02 locates an emphasis word by its turn.
- **Audit and precedent:** spark-06, audit-01 and audit-02 stopped on `ProbeInputError: dev label '5193e37ced1c026b:0:-1' lacks a verdict or evidence`.
  3 of 206 dev labels are PitBot rulings with a verdict and evidence null.
  They are now skipped; a missing verdict still stops the probe.
- 1,677 tests pass, and the new tests fail on the old code.

### 6. Reruns, rank and brief (19:50 to 19:55)

- The five reran at 19:50 (results in the table above).
- `cap-probe brief` proposed three lines; I chose two.
- Both were reworded to claim only what the probes showed:
  the router line names log-probabilities (local-01) and says agreement gave no signal on Glimmer (local-03), and the SAM line says its cost was not metered.

## Findings that matter for the design

- **spark-05's pass mark is too loose.** It passes below a Brier score of 0.25, but 0.25 is what "50% sure" every time scores.
  Spark got 5 of 10 rulings right and said 0.9 on a wrong call, so its stated confidence carries no signal yet.
- **Spark 1.3 refuses** `logprobs` with reasoning, `n` above 1 and `json_schema`; structured output works only as `json_object`.
- **SAM finds contact on a real clip** (sam-04) but holds no car identity across frames (sam-03) and raises a false contact (sam-05).
- **Voice gives turns, not words**, so a spoken verdict lines up with the replay only to the turn.
- **Precedent and audit are weak** on 12 to 30 text rulings: wrong nearest ruling, planted inconsistency missed, but no false alarms.

## Cost

| Part | Ledger |
|---|---|
| This run's paid probes (19:35 to 19:50) | $0.48 over 22 ledger lines (the two voice 502s cost $0) |
| Earlier reach and Spark probes (15:31 to 15:33) | about $0.11 |
| SAM probes (15:58 to 15:59) | not metered at the time |
| `tourney-probe` total at 19:52, shared with the steward-limits batch | $8.23 of the $20 cap |

The steward-limits journal put this run at about $0.54 of "foreign" lines inside its batch window; the ledger gives $0.48, because the journal counted a $0.10 call at 19:31 that was not this run's and left out the three reruns at 19:50 ($0.04).

## Open

- Tighten spark-05's pass mark, or run it on more rulings, before calibrated confidence goes back into the brief.
- reach-05 stays unrun while Meta's API serves no Glimmer.
- sam-06, 07 and 08 ran on placeholder frames; real track-edge, occlusion and debris frames are still to be picked.
- Voice is fallback-priced at $0.10 a call on the ledger; the real price is $0.18 an hour of audio.
