# Identity from two cameras

Date: 27 Oct 2026.
Question: does a second camera settle who is who, when Glimmer on Modal reads both streams of one incident?
Verdict: not shown.
The calls ran, and the model made one cross-camera claim that nothing here confirms.

## Inputs

Two drivers' cockpit streams of the same league race at Daytona, no telemetry.
Stream a is stream b plus 498.0 s (audio cross-correlation, z = 5.6).
Identity can only come from painted number, livery and running-order position.
The running-order panel is masked before any frame leaves the machine, because it holds drivers' names.

## Step 1: find the incident (W0-03 locator, Glimmer on Modal)

The POS box and the LAP box of stream b were cropped every 20 s and read by Glimmer on Modal.
283 reads, 0 failed calls, 11.3 minutes, 36 of 287 rows did not parse.
The raw rows were not kept, so 283 against 287 cannot be reconciled here.
A spot check against a real frame (b at 2183.5 s: POS 2 of 16, lap 40, stage lap 8) was right.
22 windows showed b losing two or more places in 20 s.
Stream a was read at the same 22 windows.
Two windows put a within one place of b: b 340 to 400 s, and b 3640 to 3700 s.
Frames from b 345 to 375 s show a multi-car crash on lap 4, with a red Toyota in both views.
The human report ("Dumped") has no known time, so nothing here proves this crash is the reported one.

## Step 2: first three-call run (invalid)

16 frames per camera at 640 px, 2 s apart, one call each for a, b and both.
All three calls reported 3,232 prompt tokens, although "both" carried twice the images.
The "both" reply described camera B only.
Cause: the Glimmer context on Modal is 8,192 tokens (set in the Modal app), so frames were cut.
These replies are discarded.

## Step 3: re-run that fits the context

5 frames per camera at 480 px, 4 s apart, shared moments 349 to 365 s of stream b.
Prompt tokens scale now: 1,240 for one camera, 2,235 for both.

| Call | Camera car read | Cross-camera match | What the model says happens |
|---|---|---|---|
| a only | blue with yellow bowtie | none | a multi-car incident ahead |
| b only | green, number 6 | none, and it says so | pack stretches out, no contact |
| both | A: black with blue, yellow and red rear. B: green, number 6 | one claim: A's camera car is the yellow and blue car ahead of B | a multi-car incident, culprit unknown, confidence 0.38 |

## What this shows

- Glimmer on Modal reads POS and lap boxes reliably, so it works as a locator.
- Camera A's car is described three different ways across the two a calls, so "who is A" is not stable.
- The only number read is "6" on camera B's car. B's frames show the camera car's own hood only at the bottom edge, so I do not trust it.
- The one cross-camera match came only in the "both" call. I have no ground truth for it.
- The model named no culprit in any call.
- Nothing here says a second camera settles identity. It also does not say it fails.

## Limits

- The window is a guess at the reported incident.
- 5 frames per camera is thin, and the context cap forces that on Modal.
- No answer key exists for who is who in this window.
- One run per condition.

## Next, if this is worth pursuing

1. Build a key by eye for this window: which car in A is which car in B, by number.
2. Raise `OLLAMA_CONTEXT_LENGTH` on the Modal app.
   That needs a redeploy and changes the router's tier 1 too, so it needs Brock's call.
3. Send crops of the cars from SAM instead of whole frames, so each image is cheap and more fit.

## Cost

Modal GPU: about 20 minutes of L40S, roughly $0.65, under the $3 cap.
Proxy-metered spend is $0.00, because Modal bills by GPU second.
The Modal dashboard holds the real figure.

## Files

- Three scripts did the work: `scan_pos.py` reads stream b, `scan_a.py` reads stream a at the same windows and `two_cams.py` makes the three calls.
- The scripts and the raw replies stay with the private tooling and never enter git.
