# Glimmer as tier-1 ruler and weak labeller on the forklift clips (27 Oct 2026)

Part A6 ran on the live Modal app (8,192-token context).
Part A3 first stood blocked by its own 32K rule; Brock chose to run it on the live app as a written amendment, made before any A3 call, and it then ran and failed.
The design it tests is pieces 7 and 9 of [the forklift scan route](../../docs/forklift-scan-route.md) (A6) and the scan-mode ruling tier (A3).
Pass marks, prompts and void rules were written down before any Glimmer call.

## Question

- A6: does the free model (Glimmer, `muse-glimmer:30b` on Modal) read hi-vis vest, spotter and raised forks on the synthetic clips the way the hand key does?
- A3: once distances are measured ([smoke test J](../2026-10-27-smoke-j-floor-distance-ruling/LOG.md)), can Glimmer write the forklift ruling, or does it take Spark Open?

## Method (A6)

- Every clip in the synthetic folder: five frames at 0.5, 1.5, 2.5, 3.5 and 4.5 s, plus the hand key's own frame where it is a different one.
  960 px wide, metadata stripped, opaque case ids.
  The synthetic clips stay out of git.
- Three separate calls per frame, one question each (vest, spotter, forks), JSON `yes`, `no` or `unsure` only, temperature 0, `max_tokens` 2048, `reasoning_effort` none, through the router proxy to Modal.
- Two runs; run 2 carries a different `user` field so the proxy cache cannot answer it.
- Scored set: the 21 clips of [smoke test E](../2026-10-27-smoke-e-hi-vis/LOG.md)'s hand key that hold at least one pedestrian with a clear vest state (15 key yes, 6 key no), scored on the key's own frame.
  Key yes means every scored pedestrian is vested; key no means at least one is not.
  An `unsure`, an invalid reply or a reply that ended on `length` counts as a miss, never as a yes.

## Result (A6)

| Mark (fixed first) | Run 1 | Run 2 |
|---|---|---|
| Vest agreement with the hand key at least 19 of 21 | **Met: 21 of 21** | **Met: 21 of 21** |
| No `yes` where the key says no (0 of 6) | **Met: 0** | **Met: 0** |
| Valid replies on at least 95% of calls | **Met: 756 of 756** | **Met: 756 of 756** |

- All 1,512 calls finished with `stop`; none ended on `length`.
- The six key-no clips (`no_vest_pedestrian_03`, `no_vest_group_near_11`, `blind_corner_no_vest_07`, `pov_forward_no_vest_close_17`, `rear_cam_no_vest_behind_20`, `B_rear_novest`) all read `no` in both runs.
- `forklift_pov_no_vest_13` is named "no vest", but smoke E's key says vested from the frames.
  Glimmer read `yes`, and this is the clip the colour script got wrong.
- Run to run, same answer on vest 251 of 252 frames, spotter 246 of 252 and forks 237 of 252.
  The one vest difference is on a superseded clip, not a scored one.

Answer mix over every frame, yes / no / unsure:

| Question | Run 1 | Run 2 |
|---|---|---|
| vest | 91 / 39 / 122 | 92 / 39 / 121 |
| spotter | 20 / 231 / 1 | 19 / 231 / 2 |
| forks | 2 / 178 / 72 | 4 / 182 / 66 |

Reported, not gated:

- Vest on the other four frames of the scored clips (run 1): never `yes` on a key-no clip.
  It said `unsure` on a later frame in five clips, where the person is small, cut off or has left the frame.
- Spotter against [smoke test F](../2026-10-27-smoke-f-reversing-spotter/LOG.md)'s labels, run 1, `yes` on how many of the 5 frames: `reversing_spotter_05` 2 (F: present), `loading_dock_spotter_08` 3 (F: present), `reversing_no_spotter_14` 0 (F: absent).
  Right on the absent clip, weak and unsteady on the two present clips.
  F has three labelled clips only, so this is a sketch, not a rate.
- Forks: no hand key exists, so no accuracy is given.
  It says `no` on most frames, `unsure` on about a quarter, and `yes` on 2 and 4 frames in the two runs.

## What went wrong in A6 (all before any answer was read)

- The void rule "prompt tokens under 600 means the image was cut" stopped run 1 on the side-by-side pair clips, whose 960 x 270 images cost 492 tokens; every other clip read 766 to 788.
  Amendment 1 moved the gate to 400; no pass mark changed.
- The abort left the queued calls running, so the rest of run 1 reached Modal and was cached while its rows were lost.
  Amendment 2 let run 1 recover its own cached replies (5 rows marked `recovered`) and cancels the queue on a void.
  Run 2 kept the strict rule and had no cache hit.
- Three new clips joined the synthetic folder while the runs went, so both runs hold 50 clips and 756 calls, not 47 and 711.
  Three later clips were not read.
  None of them is in the hand key, so they add rows and no score.

## Result (A3): first blocked, then run on the live 8,192 app, and failed

- The marks said A3 runs only on a 32,768 context with prompts of at least 5,000 tokens.
  The 32K redeploy of [Glimmer at 32K](../2026-10-27-glimmer-32k-two-cameras/LOG.md) had been rolled back, because its 64-image call dropped frames.
- A probe call with smoke J's real prompt read 3,982 prompt tokens, five frames included, so the frames fit; the 12,000-token reply budget did not.
  The 5,000 gate was my guess from Spark's image size and was wrong for Glimmer.
- Brock chose to run it anyway.
  Amendment 3 changed only the run conditions: the live 8,192 app, a prompt gate of 3,500 tokens, `max_tokens` 3,500, `reasoning_effort` none, and a `length` finish counted as a fail.
  The pass marks did not change.

Method: smoke J's six windows, five frames at 960 px, J's fact sheet with the measured distances, J's rules with the site's 3 m, seeded case ids, J's post-check, temperature 0, two runs (run 2 with a different `user` field, no proxy cache hit).
Only the model changed, from Spark Open to Glimmer.

| Window | Key | Glimmer, both runs | Spark Open (smoke J) |
|---|---|---|---|
| `loading_dock_spotter_08` | none | separation breach (0.6 m, "moves forward toward the dock") | separation breach |
| `vest_group_cross_10` | none | separation breach (0.9 to 1.1 m, "moves toward the crossing") | separation breach |
| `spotter_ahead_01` | none | separation breach (2.4 m, "moving toward two pedestrians") | separation breach |
| `no_vest_pedestrian_03` | hi-vis | hi-vis breach found, plus a separation breach (0.4 m) | same |
| `bump_upright_cctv_25` | structure contact | **no breach on any rule** | structure breach found |
| `reversing_no_spotter_14` | spotter when reversing | **no breach on any rule** | no breach on any rule |

| Pass mark (fixed first) | Run 1 | Run 2 |
|---|---|---|
| No compliant window has a breach | **Not met**: 0 of 3 clean | **Not met**: 0 of 3 clean |
| 3 of 3 labelled windows ruled under the right rule only (strict) | **Not met**: 0 of 3 | **Not met**: 0 of 3 |
| The two runs agree on every verdict of every finding | Met | |
| Every call finishes with `stop` | Met: 12 of 12 | |

- Lenient reading (right rule found, extras allowed): 1 of 3 for Glimmer (only window 03), against 2 of 3 for Spark Open.
- Prompt tokens were 3,969 to 4,037 on all 12 calls, so the five frames were in and the 3,500 gate held.
  Completion tokens were 660 to 1,204, so the 3,500 reply budget was never close.
- The runs match on all 12 verdicts, and completion tokens match exactly on five of six windows, so temperature 0 is steady on this app.

## What it shows

- Glimmer at tier 1 is a usable vest labeller on these clips: 21 of 21 against the hand key in both runs, with no false yes.
- The compliant windows fail A3 for the reason smoke J gave: each has a person under 3 m and the sheet carries no truck speed, so the model reads the truck as moving from the frames.
  That is a missing fact, not model skill, and both models fail it the same way.
- The two labelled misses are new for Glimmer on the structure rule (Spark found it) and shared with Spark on the reversing rule.
  The reversing miss is the direction read that piece 9 does by script.
- Tier 1 does not write the forklift ruling today.
  Spark Open stays the ruling tier for scan mode, at about $0.02 a window, and truck speed has to be added to the fact sheet before either model can pass.

## Cost

- Modal dashboard, read at 20:10 on 27 Oct: the Glimmer app billed $2.60 between 17:00 and 19:00.
  This experiment and [Glimmer at 32K](../2026-10-27-glimmer-32k-two-cameras/LOG.md) ran on the same app in the same hours, so the dashboard cannot split the $2.60 between them.
- Before the dashboard was read, A6 was estimated at about 55 to 60 minutes of L40S, $1.80 to $2.00 at $1.95 an hour, against a forecast of $0.90 and a ceiling of $1.30.
  Calls took 6 to 8 s each on 4 workers against the 2 s forecast, because each call produced about 130 completion tokens even with `reasoning_effort` none.
- A3 added 13 calls (12 runs plus the probe), estimated at 8 to 10 minutes of L40S, about $0.30.
- Proxy-metered spend: $0.00, because Modal bills by GPU second.
  No Meta, Baseten or SAM call was made.

## What it does not prove

- The clips are AI-made, so a pass is an upper bound.
- The hand key is one person's eye on one frame per clip, and the same eye drew the colour script's key, so Glimmer agreeing with it is not independent proof of what the frames show.
- 21 scored clips, 6 of them key no: 21 of 21 is a good sign on a small sample.
- The question asks whether every person on foot wears a vest; it does not ask who, where or how many.
- Spotter has three labelled clips and forks has none.
- Frames were scaled to 960 px; real cameras, night and dirty vests are not exercised.

## Needs

- Scan-mode rulings stay at Spark Open (tier 2) for forklifts; Glimmer at tier 1 is a labeller (A6), not a ruler (A3).
- Truck speed on the fact sheet (piece 6 with piece 8) before a rerun of either model.
- A person to redraw a sample of the hand key before the vest result is quoted as more than this test.

## Files

The marks, the three amendments, the labelling and ruling scripts, the results and the A3 replies and findings are kept with this experiment's private record.
The frames and the raw call rows stay out of git.
