# Steward limits: experiment log (26 Oct 2026)

What we ran to find out what a video-only steward on Meta's models can do, how we ran it, what it cost and what we learned.

## Question

Given a driver's incident report and the evidence clip, can the steward:
1. work out who is who on screen,
2. find which incident the report means when the clip holds several,
3. rule correctly (penalty, racing incident or no action, with offender and victim),
4. show evidence a human steward can check?

Telemetry is never an input.
It may serve only as an answer key for grading.

## How it runs (technical)

- Every Meta call goes through the metering proxy, run `d0`, on 127.0.0.1:8765, under the `tourney-probe` token.
- The proxy runs from the scheduled task "ai-steward d0 proxy" (`runs/d0/proxy-loop.ps1`), which restarts it 60 s after any exit.
- Each call is a line in `runs/d0/spend.jsonl` (the ledger).
- Probe cap: `TOURNEY_PROBE_CAP_USD`, raised from $5 to $10 on Brock's word on 26 Oct and to $20 at 19:35 Chicago, set in `proxy-loop.ps1`.
- Models:
  - `muse-spark-1.3`: chat completions with images, $1.25 in / $4.25 out per 1M tokens.
  - `muse-wonder-1.0`: same API, $4 in / $20 out per 1M tokens.
  - `sam-3.1`: served only on `/v1/responses`, $0.0025 an image, $0.0002 a video frame, 50-frame minimum per video call.
- SAM request: an `input` message with an `input_text` part and an `input_image` or `input_video` part (base64 data URL), `stream: false`.
- SAM prompts: a noun phrase ("race car", one concept per request) or box prompts `<Nf>1<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H|>` on prompt frame N.
- Box prompts return one-bit masks only; soft (0-255 coverage) masks come only from noun-phrase prompts.
- SAM replies are parsed with Meta's `meta-sam-parser` 0.1.0 (SAM License: use and modify allowed, acknowledge SAM in publications).
- Code changes made for this work: `cced00d` (SAM probes call the Responses API), `acf2b30` (the proxy charges SAM for images and frames).
- Scripts are in `scripts/`; they run with `.venv/Scripts/python.exe -I` because `uv run` cannot sync while the proxy holds `tourney.exe`.

## Data

- Two public steward-stream clips: window 1193.8-1244.4 s (steward: penalty for avoidable contact) and window 1352.6-1364.7 s (steward: no action).
- Reports from a PitBot league whose resolved incident reports are the answer key ("the league" below): a read-only export of 32 resolved incidents (28 penalties, 4 no action) from the league's PitBot database, kept out of git.
- The league's clips, downloaded with yt-dlp: reports 9 and 13 (short clips), 10, 15 and 46 (full races).
  Five Google Drive clips refused (403/404, not shared), one Discord message link, one local file path.
- The ruling text (`ruling_reason`) is the answer key and never goes into a steward prompt.

## Runs, in order

Runs 1 to 9 ran on 26 Oct, 15:46 to 17:26 Central, by the ledger's timestamps.

| # | What | Inputs to the model | Result | Cost |
|---|---|---|---|---|
| 1 | SAM image mode, noun phrase, per frame | single frames | Object ids reset per frame; box overlap gave a false "contact" on both clips | SAM before the meter fix: logged at $0, see Spend below |
| 2 | SAM video mode, noun phrase | steward clips | Ids stable; boxes overlap in 57% (contact) vs 46% (clean) of frames, so boxes do not discriminate; hard masks never overlap | in row 1 |
| 3 | SAM video, cropped race panel + confidence, soft masks | cropped clips | Soft overlap ≥5%: contact 30/223 frames vs clean 0/61; but missed the spinning car and merged distant cars | in row 1 |
| 4 | Spark names cars, SAM box-prompt tracking at 30 fps | 8 frames, then 3 s clip | Gap between two cars falls from 271 px to 1 px for 11 frames at 1234.10-1234.43 s; 1 px is evidence, not proof (occlusion) | Spark $0.036, SAM in row 1 |
| 5 | Hands-off chain: Spark triage at 1 fps, SAM per episode, Spark ruling | 50 s window, no report | Contact clip: no action (wrong); clean clip: racing incident (right direction, no penalty). Five spins in 50 s; the chain cannot tell which one the steward meant | $0.14 + $0.10 (estimated) |
| 6 | Spark only, league report #9 | reporter "<driver>", description "Race 3 lap 1", 22 frames at 1.5 s | Penalty, #959 put #555 into the wall at 27 s; right offender and victim; chose 1 of 6 contacts; read the reporter's name in the replay overlay | $0.050 (estimated from usage) |
| 7 | Spark only, league report #13 | reporter's name and full written account, 22 frames at 3 s | Penalty, #44 squeezed #26 off at Turn 1; right | $0.024 (estimated from usage) |
| 8 | Run 6 with the race-control chat blacked out | as run 6 | Same correct ruling from the cars alone; the chat had printed "Car #959 Contact", a give-away | $0.048 (estimated from usage) |
| 9 | Meter check after `acf2b30` | 1 SAM image | Ledger line `images_processed: 1`, `usd: 0.0025`, not estimated | $0.0025 (measured) |

Spend: $0.330 measured on the ledger for runs 1 to 9 (48 lines; the ledger stood at $0.445 after run 9, the rest being the capability probe's calls).
The 31 SAM calls among those lines came before the meter fix, so the ledger logs them at $0 with no frame count; their cost was estimated at about $0.21 early on and about $0.47 later, and the ledger cannot settle which.
Brock's dashboard showed $149.74 left after run 3, which matched the reconstruction.

## Findings from runs 1-9

1. Spark judges well when it has a report; SAM alone misleads (occlusion reads as touching, results vary run to run). Spark rules, SAM supplies frame-level evidence.
2. The report is what picks the incident. Without it, a 50 s clip with five spins has no single answer.
3. Identity comes from the screen: the replay overlay names the camera's driver, and car numbers are readable.
4. The PitBot roster is wrong for past races: three drivers named in the league's rulings are no longer in the `drivers` table, and car #44 now belongs to someone else. Name from the screen first; roster is a flagged fallback.
5. The same design carries to forklifts: a visible marker (fleet number) plus the site's own roster, never faces, which also keeps inside Meta's acceptable use policy.

## PitBot gaps found (for after the hackathon)

- Reports have no accused or reporter roles, no lap, no video time and no car numbers as fields.
- `penalty_driver_id` is empty on 24 of the league's 28 penalties; the offender is only in the ruling text.
- Car numbers are stored per series, not per race.

## The 25-run batch

It ran on 26 Oct, 17:33 to 18:06 Central (the journal's start and end lines).
A Fable agent (Claude, on the subscription; no Meta spend of its own) designed and ran 25 runs through the same proxy, batch budget $5 on the ledger.
Groups: A identity, B which event (full races), C ruling depth (Wonder, panel, consistency, frame spacing, image size), D evidence (SAM touch frame, evidence image, rule citation), E robustness, F forklift.
The agent kept a results table with per-run lessons, one JSON line per run, a run journal with every deviation and ledger reading, and its scripts; the frames are not in the repo.

- Spend: $1.998 measured on the ledger (probe total $0.445 to $2.443); the 25 per-run costs sum to the same figure.
- Scoreboard (checked against the per-run JSON lines): 18 right, 4 wrong, 3 not scorable.
- Wrong: run 3 (no written description: penalty became racing incident), run 7 (cockpit stream: moment not found), run 16 (SAM's 1 px gap read as touch 1.5 s early), run 25 (a light bump read as no contact).

Batch findings:
1. Spark rules on consequences: verdict and roles held through masked overlays, 320 px, 3 s spacing and heavy compression, but it dates the hit 0.6-1.5 s early, and SAM's 1 px gap runs 1.8 s before the real touch. SAM dates the spin onset precisely (within 2 frames).
2. A `report_problems` field costs nothing and caught a wrong car number, a wrong lap, a report ordering a penalty, a false contact claim and a league number that differs from the on-screen number.
3. Broadcast footage is solvable: a scan of the flag/lap strip gives the session structure for $0.08-0.14, and a deterministic race/lap selector found the human's moment to the second on one race. Cockpit streams are not solved yet.
4. Operating point: Spark, 1280 px, 1.5 s spacing. Wonder ran out of output at 8k tokens and cost 9x Spark at 640 px with lower confidence. A three-role panel kept the verdict and sharpened the argument: worth it for appeals only.
5. Identity comes from the screen: with both overlays hidden it read the number off the car body; without numbers it ruled by livery and said "reporter unknown" rather than guess. Digits slip on some passes, so confirm a number from a second frame.

Surprises: the proxy returns cached replies for identical requests ($0), which voided the first consistency attempt; temperature 0 is not deterministic (timings vary, the ruling did not); smaller images were not cheaper, because Spark reasons longer on worse images.

## Batch 2: 33 tests from the follow-up test list

It ran on 26 Oct, 18:53 to 19:52 Central (the journal's start and end lines).
A second Fable agent ran every test in the follow-up test list except F4 (no footage with a fleet number), with the B2 benchmark (18 stream windows scored against the human steward's spoken verdict, with the words withheld from the model) at the full 18 items.
It kept a results table with design findings, per-model limits and next tests, one line per test, a run journal with ledger readings and 13 deviations, and its scripts.

- Spend: $5.14 measured from the batch's own calls (checked: the per-test costs sum to $5.143).
- The ledger rose $5.79 over the same window ($2.444 to $8.232): $5.154 on the batch's own 165 lines ($0.011 above its per-test costs), $0.48 from a separate `cap-probe run` of the remaining battery (audit, cross, voice, wonder, spark-05/06, spark-vision-contact) and a `cap-probe rank` from outside this run (22 lines, 19:35-19:50 Chicago), $0.056 from five task-router Spark Open calls, and one $0.10 line at 19:31 that no log claims.
- Hypotheses: 9 held, 15 partly, 9 failed. Against an answer key: 18 right, 5 wrong, 10 not scorable (checked against the per-test lines).

Findings that change the design:
1. Thin reports are the weak spot: with no written account, Spark reversed roles on #13 even with dense frames; Wonder at medium effort got the penalty right for $0.085.
2. On 18 human-steward windows with no report, Spark scored 5/18: it called ten of 13 penalties "no action" and gave no false penalties. Five human penalties were for non-contact offences, which a contact-only code never names.
3. Spark takes time from frame labels, not images (reversed frames labelled forward were narrated forward). The yaw-rate step on SAM box masks dated #9's loss of control at 27.73 s, inside the 27.6-27.9 s truth: the first measure in two batches to land there.
4. Stability: 2 of 31 fresh #9 rulings named the camera car as offender, so contested rulings need two calls. A 4x upscaled SAM crop reads the car numbers right for $0.001.
5. `reasoning_effort` is a free lever: minimal keeps the #9 ruling in 8 s against 62 s at max. Wonder finishes at low effort. Strict `json_schema` works with images.
6. No 50-image cap on either API, but 120+ frames reason to the 8k output ceiling and never rule. No prompt-cache discount is reported. Ten parallel calls gave no 429 errors.
7. Audio: Spark 1.2/1.3 hear nothing from a video. Voice on multipart `/v1/asr/transcribe` works through the proxy with a word error rate of 0.10-0.14, but says "Yeah." on silence. Loudness peaks 4-7 s after a contact: good for finding an incident in a long stream, not for timing it.
8. SAM: confidence never flags occlusion. Pack tracking churns (16 ids, 56 id jumps). Data URLs of 19-27 MB fail unless `store=false`. `file_id` works, and 1,500 frames cost $0.30 in 75 s. The forklift bump is a 0 px gap for 29 frames, so batch 1 run 25 was a model miss, not a label fault.
9. Spark Open read a spoken verdict for $0.0035 and, on native video, dated the #9 contact at 28 s, the closest yet. It allows 8 images and reads no numbers, and `detail` does not change its token count.

Known meter fault: voice calls report no model, so the ledger prices them at the highest fallback row ($0.10) instead of $0.05 or less.
