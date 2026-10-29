# Discovery 3 results (26 Oct 2026)

Discovery 3 is the third round of tests, after the two steward-limits batches, run on 26 Oct from 21:02 to 21:51 Chicago time.
phN names one clip of league footage that the drivers' incident reports point to; W0 tests are free and run locally with no paid call, W1 tests are small, independent paid tests, and W2 tests run the steward end to end as an agent that gathers its own evidence.

Twenty-six of the 28 tests in the follow-up test list ran, one Fable agent per test, in parallel.
W0-03 (local Glimmer reading the lap-timer strip across two camera streams of one race, hours of GPU; a separate pass from the router's label work) and W1-16 (which needs it) wait for the Modal GPU.
Each test's full record and notes were kept with the run.
Frames and clips are not in the repo.

## Spend

- Paid calls: $5.59 measured, the sum of the 21 paid tests' own ledger lines.
- The probe ledger rose from $8.23 to $13.82 over the run, the same $5.59, under the $20 cap.
- Five tests ran at $0 (telemetry and local Glimmer only).

## Scoreboard

| Test | What | Result | Cost |
|---|---|---|---|
| W0-01 | report 15 stream offset from telemetry | 3808.5 ± 1.5 s; contact at video 4341-4344; camera car is the replay's #70 | $0 |
| W0-02 | Catalogue of every contact in the replays | 58 events, 40 paired, 21 on video; the key's 12 cases all found | $0 |
| W0-04 | Glimmer reads the broadcast clock strip | 7 of 7 finished reads digit-exact; 36-600 s a read on the shared GPU | $0 |
| W0-05 | Penalties from incident counts alone | 5 of 8 reports reproduced; the per-lap counts undercount | $0 |
| W0-06 | Contact detector from 1 Hz positions | Failed: best recall 55% at 49 false alarms per 10 min | $0 |
| W1-01 | Spark timing baseline, five clips | Timing within 1 s on 4 of 5; verdict 2 of 5, roles 1 of 5 | $0.345 |
| W1-02 | Dense 0.5 s frame pack | 2 of 5; the key's report 46 window starts 3 s after the visible contact | $0.156 |
| W1-03 | Spark Open on native video | Verdict 5 of 5; offender by number 2 of 5; timing within 1 s 1 of 5 | $0.055 |
| W1-04 | SAM yaw step on broadcasts | 0 of 3; every firing was a camera cut or the mask | $0.219 |
| W1-05 | Read car #01 off the report 46 broadcast | 0 of 7; the car is never wider than 119 px | $0.027 |
| W1-06 | No-action case, report vs no report | Not scorable; the report alone moved racing incident 0.6 to penalty 0.8 | $0.153 |
| W1-07 | Spark on telemetry facts only | Verdict 7 of 12, with offender 6 of 12 | $0.095 |
| W1-08 | Spark Open and Glimmer on facts only | Spark Open 3 of 11; Glimmer 0 (thinking used every token) | $0.112 |
| W1-09 | Facts plus frames | 2 of 4 right; report 13 acquitted because +0 was read as no contact | $0.365 |
| W1-10 | Reasoning effort minimal vs high | Minimal 2 of 5, high 1 of 4; high broke the JSON on 2 of 5 | $0.446 |
| W1-11 | Two calls must agree | 1 of 3; a third of calls at 8,000 tokens returned nothing | $0.319 |
| W1-12 | Wonder at low effort | 1 of 3; rules on whichever car is in shot | $0.457 |
| W1-13 | Commentary audio | No car numbers spoken; Spark Open dated one contact to the second | $0.209 |
| W1-14 | Precedent matching | 7 of 12, below always-penalty's 10 of 12 | $0.128 |
| W1-15 | Forklift on Spark Open | 19 of 20 with the filename in the prompt, 11 of 20 without | $0.445 |
| W1-17 | Three incidents in one 141-frame call | 0 of 3; the model miscounts frames, times drift about 30 s | $0.075 |
| W1-18 | report 15 from the offender's cockpit | Penalty and timing right (0.0 s); identity taken from the on-screen label | $0.036 |
| W2-01 | Agent plans its own evidence (Spark) | Verdict 6 of 6, roles 4 of 6; asked for telemetry first every time | $1.268 |
| W2-02 | Planning only, three models | Spark Open 12 of 12, Spark 11 of 12, Glimmer 0 of 3 | $0.101 |
| W2-03 | End to end, six keyed clips | 4 of 6 verdict and offender; contact found within 3 s on 4 of 4; under $0.10 a case | $0.314 |
| W2-04 | Spark Open drives the tools | Tools work on Baseten; with telemetry 1 of 2, without 0 of 2 | $0.265 |

## Findings that change the design

1. The pipeline finds the moment; it fails on who is who.
   Timing landed within 1 s on most clips (W1-01, W2-03, W1-18), and the misses were identity: misread digits, on-screen labels trusted over the car, or a touch the camera never showed.
2. Telemetry gives the second, not the blame.
   Spark and Spark Open read counters literally: both +4 became shared fault (W1-08), a forced-off car with +0 was acquitted (W1-09), and a gap trace was read as blame (W2-01 report 13).
   The blame rule has to be in the prompt, including "a car forced off registers no incident points".
3. The agent shape works.
   Spark asked for telemetry first whenever it had the tool (W2-01), and Spark Open drove the same tools on Baseten (W2-04) and wrote the best plans at about $0.005 each (W2-02).
   Meta's API has no way to switch tools off, so the harness must send "tools are closed" to get a ruling (needed on 3 of 6 runs).
4. Output headroom is a correctness setting.
   At 8,000 output tokens a third of strict-schema calls reasoned to the ceiling and returned nothing (W1-09, W1-11, W1-17); 16,000 fixed every one (W2-03, 0 truncated).
5. Minimal reasoning effort is the triage setting: same or better rulings, 0.27 of the output, valid JSON every time (W1-10).
6. A second call on low confidence bought nothing for $0.08 (W2-03), and a report can tip a borderline ruling (W1-06).
   So every report-swayed ruling ships with its frames as a second opinion, never an override.
7. Label every frame with its video second in the text; the model miscounts frames in long packs (W1-17).
8. Broadcasts need a shot-cut gate before any SAM measure (W1-04), and the identity frame should be chosen by SAM box size, not by fixed seconds (W1-05).
9. Local Glimmer failed three times the same way: it spends its whole token allowance thinking (W1-08, W2-02) and runs 36-600 s a call on the shared 12 GB GPU (W0-04).
   The Modal runs need a far higher token limit as well as the GPU.

## Corrections to earlier records

- Report 15: W0-01 measured the contact at video 4341-4344 s, so batches 1 and 2 (4336-4342) were right and the earlier discovery notes' 4405-4425 was wrong.
  The camera car is the replay's #70, the offender; the on-screen race-control line says "Car #32", which is unresolved.
- Report 46: the visible contact is at 1139-1140 s (measured in W1-02), before the key's window.
- Report 13 shows the same contact twice; the second angle is at about 33-36 s.
- Forklift: batch 1's 19 of 20 put the clip's filename, which names the label, in the prompt; with an opaque case reference it is 11 of 20 (W1-15).
- W2-03's report 14 knew the camera car from W0-01's telemetry sync, so that case is key-assisted.
- The scorer scored a leading-zero number ("01") wrong; fixed during the run, so W1-07's offender score is 6 of 12, not 5.
- The per-test budget read the shared ledger, so parallel tests tripped each other's caps; every test capped on its own calls instead, and resumed where it had stopped.

## Waiting

- W0-03 and W1-16 run on the Modal GPU ($30 limit), with a higher Glimmer token limit; W0-03 reads the race footage and is not the router's label pass.
- Which number is right for report 15's camera car, #32 on screen or #70 in the replay.
