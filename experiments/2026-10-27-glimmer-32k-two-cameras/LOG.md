# Glimmer at 32K on Modal, and identity from two cameras again (27 Oct 2026)

Status: run on 27 Oct 2026.
A1 failed its fixed mark and A2 was not testable.
The Modal app was rolled back to its 8,192-token context at the end of the run.
Every mark below was written before the first model call and did not change after it.

## Question

A1: with the 8,192-token context removed, does a second camera settle who is who?
This reruns [Identity from two cameras](../2026-10-27-identity-two-cameras/LOG.md), which the context cap had forced down to 5 frames a camera.
A2: can Glimmer on Modal walk both whole racing streams at 5 s steps and return the incident windows?

## Method

A1:

- Redeploy the Glimmer app on Modal with a 32,768-token context, keeping the 8,192 version as the rollback.
- Rerun the three calls (camera a, camera b, both) at 16 frames a camera, 640 px, 2 s apart, over b 361 to 391 s (a = b + 498.0 s), with the running-order panel masked because it holds drivers' names.
- Check the prompt token count scales with the frames.
- Then 32 frames a camera at 1 s steps over b 361 to 392 s.
- Each of the three calls runs twice at temperature 0, seeds 1 and 2, every call a proxy cache miss.
- A hand key was built by eye before any call, from full-frame stills of both streams.

A2: crop the POS and LAP boxes every 5 s on both streams, read them, flag windows, read a 4-frame strip at each flag, and score against the known incidents.

## The hand key

| Id | Camera | Car |
|---|---|---|
| A-car | camera a follows it | black Ford with blue stripes and yellow script on the rear, number 39 |
| B-car | camera b follows it | dark red and black Toyota with green lettering on the rear |
| Red 8 | neither | red Chevrolet, white number 8 |

Cross-camera pairs the frames confirm:

| Pair | Where it shows | Confidence |
|---|---|---|
| A-car is the 39 in view b | b 375 s: the black, blue and red car with a 39 passes B-car on its left | high |
| B-car is the green-lettered car in view a | b 373 to 375 s: it enters the right edge of view a | high |
| Red 8 in view a is red 8 in view b | view a, b 361 to 369 s, passing A-car; view b, b 378 to 391 s, passing B-car, number readable in both | medium to high |

A claimed pair is confirmed if it matches a row, contradicted if it names one of the three cars as any car not in its row, and otherwise counts neither way.
No crash is visible in either view over b 361 to 391 s: the stills show a pack running at 183 to 194 mph and a pass.
So the lap 4 "crash" named in the first two-camera log was a guess and is wrong.

The window moved from the first log's b 345 to 375 s to b 361 to 391 s before any call, because the earlier window held only 2 pairs the frames confirm and the mark needs 3.
Brock chose this.

## Pass marks (fixed before the run)

- A1 passes if, in both runs of the "both" call at 16 frames a camera, the call names at least 3 pairs the key confirms and 0 it contradicts.
- The "both" call's prompt tokens must be more than 1.8 times one camera's; if not, frames were cut and the run is invalid.
- The 32-frame call is scored the same way and reported beside it, but only the 16-frame result decides.
- A2 passes if both known incidents sit inside a returned window and no more than 1 window comes back per 10 minutes of green running.
  The known incidents come from the PitBot labels with times; if fewer than 2 have times on these streams, A2 is reported as not testable.

## A1 result

The 32K deploy started, held its access lock, and answered through the router proxy; the app log showed a 32,768 context on each of its 4 slots.

| Condition | One camera | Both cameras | Ratio | Frames cut? |
|---|---|---|---|---|
| 16 frames, 640 px, 2 s | 5,333 | 10,421 | 1.95 | no |
| 32 frames, 640 px, 1 s | 10,421 | 13,090 | 1.26 | yes: 64 images need about 20,800 |

The 16-frame call is valid by the mark, and the 32-frame "both" call is not.

| Call | Confirmed pairs | Contradicted | Note |
|---|---|---|---|
| 16 frames, both, run 1 | 1 (red 8) | 0 | also claims a black and yellow car in both views, not in the key |
| 16 frames, both, run 2 | 2 (red 8, A-car as the 39 in view b) | 0 | |
| 32 frames, both, run 1 | 0 | 0 | prose, not the JSON schema, and it starts camera A at 23 s, so its first frames were dropped |
| 32 frames, both, run 2 | 0 | 0 | the same, and it says the two views are "not in sync" |

**A1 fails on the fixed mark**: it needed at least 3 confirmed pairs in both runs, and the runs gave 1 and 2.
Nothing was contradicted.

- Both 16-frame runs describe a multi-car incident (a spin, a wall hit, a car "collected").
  The key records no crash in the window, so the incident is invented.
- Camera B's car is read as number 2; the 2 is the pit-strategy icon on the HUD, not a number on the car.
- The A-car's livery is "blue and yellow" in both runs, where the key says black with blue stripes.
  Run 2 got the car right only by its number, 39.
- The two 16-frame runs differ at temperature 0, so the call is not repeatable even on the same frames.

## A2 result: not testable

The A2 mark needs known incidents with times on these two streams, and none exist.
The reported incident on them has no known time, and the labelled reports with times sit on short PitBot league phone clips, not whole broadcasts.
The first log's two windows (b 340 to 400 s and b 3640 to 3700 s) are where the camera car lost places, and the stills of the first show a pack, not a crash.
Under the rule written before the run, A2 is reported as not testable, and no GPU was spent on it.

## What this does not prove

- It does not show that a second camera never helps.
  It shows that at 16 frames a camera, 640 px, over one 30 s pass, Glimmer named 1 and 2 of the 3 pairs the key holds, and invented an incident.
- It does not show that 32K works.
  The app reported 32,768 per slot, but the 64-image call came back at 13,090 prompt tokens with its first frames gone.
  The cause was not found: it could be the image count, the Ollama runner or the proxy, and I did not test which.
- The key is one person's eye on 1280 by 720 stills, and the red 8 pair is medium to high, not certain.
- One window, one race, two runs.
- A2's real question, whether the model can locate incidents in a whole broadcast, is untested.

## Cost

- Modal dashboard, read at 20:10 on 27 Oct: the Glimmer app billed $2.60 between 17:00 and 19:00.
  This experiment and [Glimmer as forklift ruler](../2026-10-27-glimmer-forklift-ruler/LOG.md) ran on the same app in the same hours, so the dashboard cannot split the $2.60 between them.
- Before the dashboard was read, this run was estimated at about $0.90 of L40S (12 A1 calls, two check calls, a cold start and the idle window after each burst, at $1.95 an hour) plus about $0.07 for each redeploy.
- Proxy-metered spend is $0.00, because Modal bills by GPU second.
- No Meta, Baseten or SAM call was made.

## Rollback

Done at the end of the run.
The 8,192 version was redeployed to the same address, so the router needed no change.
A call through the router proxy answered, and the app log showed an 8,192 context per slot.
The 32K version is kept in the private tooling as the way back.

## Needs

- A real incident with a time on a long broadcast stream before A2 can be scored: find the reported incident's time by eye, or pick a stream with telemetry.
- The cause of the dropped images at 64 images: send the same body straight to the Modal app, or lower the image count to find where it stops.

## Files

The script, the hand key's stills and the raw replies are kept with this experiment's private record, and the frames never enter git.
