# League catalogue: seven races, stream clock, feed events, steward decisions (28 Oct 2026)

Scripts only: no model, no SAM, no proxy call, $0.
Scripts measure everything; nothing here is a model's judgement.
The league is a PitBot league; its name, its drivers' names and its stream ids stay out of this repo.
Car numbers, track names and decision ids only.

## Question

Can scripts alone, from seven race broadcasts and the league's replay feed, fix each stream's clock to the feed, list the feed's events, and join the league's 32 steward decisions to them?
If so, the league becomes a test bed for scanning a whole broadcast, scored against data no model wrote.

## Pre-registration (written and committed before any stream frame is read)

### Inputs

- Seven races with a broadcast stream and a replay feed from PitBot's companion.
- The league's 32 steward decisions, exported from its PitBot database.
- Per-lap rows (lap time, incidents on that lap, pit) for the drivers whose companion uploaded.

The feed fields were profiled before this section was written, and no stream frame was read before its commit.

### The method, fixed in advance

1. Feed update rate, measured first because Brock said the older feeds update positions only when a lap completes: the share of frame pairs where a car's track position (`pct`) changed, the frame cadence, and the spread of each car's speed.
2. Clock alignment, with smoke B's strip reader and templates unchanged: `video_t = te + offset`.
   Every keyframe of every stream is read; sessions are split by the TIME constant; each cluster is tried against each feed session with the LAP witness.
   A session is aligned when one cluster gives a LAP bracket no wider than 4 s.
   The TIME witness is recorded beside it and never used alone.
   Check marks: the Oulton HEAT 1 offset must come out 1394 ± 2 and the Cadwell HEAT 1 offset 977 ± 2, the two offsets fixed by hand before.
3. Feed events, thresholds fixed here:

| Event | Rule |
|---|---|
| Gap collapse | two cars go from a gap of 8.0 m or more to 2.0 m or less within 3 s, neither in the pit; the same pair within 10 s merged |
| Collapse with stall | either car's 1 s mean speed falls under 12 m/s within 5 s after |
| Collapse with incident rise | either car's shown incident count rises within 2 s before to 5 s after |
| Incident rise | every rise of a car's shown incident count |
| Paired +4 | W0-02's method unchanged at 8 m: two +4 rises whose bounds overlap, the cars within 8 m |
| Battle | a pair the feed lists as battling for 5 s or more |
| Caution | any second the flag is not green or a caution is set |

4. Decision join: the race comes from the ruling text's race number, then the form fields, then the latest race day on or before the decision.
   Every disagreement between the three is recorded, never silently resolved.
   A decision matches an event when the session is the same, the event holds every named car, and the leader lap is within ±1 of the stated lap.
   An incident-total decision matches a car whose final shown count equals the stated total.
5. Every script runs twice and the two runs must hash the same.

## Results

### The feed is live, not lap-step

| Race, session | Frames | Share of 1 s steps | Share of frame pairs where pct changed | Speed spread (CV) |
|---|---|---|---|---|
| Oulton HEAT 1 | 373 | 0.50 | 0.999 | 0.42 |
| Spa RACE | 5556 | 0.96 | 0.999 | 0.37 |
| Snetterton HEAT 1 | 1625 | 0.53 | 1.000 | 0.51 |
| Snetterton FEATURE | 1582 | 0.49 | 1.000 | 0.46 |
| Brands Hatch HEAT 1 | 2465 | 0.97 | 0.990 | 0.34 |
| Brands Hatch FEATURE | 2591 | 0.98 | 0.989 | 0.35 |
| Donington RACE | 5289 | 0.91 | 0.985 | 0.42 |
| Cadwell HEAT 1 | 1644 | 0.94 | 0.982 | 0.39 |
| Cadwell FEATURE | 1765 | 0.98 | 0.984 | 0.37 |
| Thruxton HEAT 1 | 1200 | 0.90 | 0.990 | 0.36 |
| Thruxton FEATURE | 1148 | 0.81 | 0.995 | 0.36 |

- A lap-step feed would hold `pct` still between lap lines, so a change share near 0 and no speed spread.
  Every session shows `pct` moving on 98% or more of frame pairs, with real speed spread.
- Gap collapses come with a car stopping mid-lap and an incident rise at the same second, 13 of them in Snetterton HEAT 1, the oldest feed.
- The real difference between older and newer feeds is cadence: Oulton and both Snetterton sessions write a frame about every 2 s, the rest nearly every second.
  Read their event counts as lower bounds with 2 s timing.
- Oulton HEAT 1 covers only about 9 minutes (leader laps 1 to 7) and shows no incident counter; Oulton FEATURE has no feed rows.
- These figures hold for these seven races only, so Brock's word on earlier races stands until he checks.

### Clock alignment

| Race, session | Stream | Offset (s) | Lap edges agreeing | Lap-sequence match (reads) | TIME witness |
|---|---|---|---|---|---|
| Oulton HEAT 1 | Oulton | 1395.5 | 6 of 6 | 1.00 (60) | 1559.0 (the known 166 s gap) |
| Spa RACE | Spa | 1502.5 | 17 of 18 | 0.88 (597) | 1503.0 |
| Snetterton HEAT 1 | Snetterton | 2063.0 | 11 of 13 | 0.86 (280) | 2063.0 |
| Snetterton FEATURE | Snetterton | 5040.0 | 13 of 17 | 0.93 (243) | 5042.0 |
| Brands Hatch HEAT 1 | Brands Hatch | 1496.4 | 9 of 14 | 0.96 (271) | 1492.8 |
| Brands Hatch FEATURE | Brands Hatch | 4453.3 | 12 of 14 | 0.95 (264) | 4454.8 |
| Donington RACE | Donington | 1446.0 | 33 of 34 | 0.92 (720) | 1446.0 |
| Cadwell HEAT 1 | Cadwell | 976.5 | 16 of 16 | 0.98 (258) | 978.0 |
| Cadwell FEATURE | Cadwell | 2941.0 | 17 of 17 | 0.99 (297) | 2941.0 |
| Thruxton HEAT 1 | Thruxton | 1042.0 | 13 of 13 | 0.98 (177) | 1042.0 |
| Thruxton FEATURE | Thruxton | 2624.5 | 13 of 14 | 0.98 (177) | 2625.0 |

- **Both check marks pass**: the Oulton HEAT 1 offset at 1395.5 against 1394 ± 2, the Cadwell HEAT 1 offset at 976.5 against 977 ± 2.
- All 11 race sessions with a feed are aligned, across seven streams and about 14.7 hours of video.
- The TIME witness, never used to choose, agrees within 2 s on 9 of 11.
  The two exceptions are the Oulton HEAT 1 offset, with the 166 s gap smoke B found, and Brands Hatch HEAT 1 at 3.6 s.
- Keyframes sit about 5 s apart and the feed second is whole, so take ±2 s as the floor for every offset, and ±4 s for Brands Hatch HEAT 1.
- Spot checks by eye, frames only: the Spa strip's lap 2 to 3 change sits at the Bus Stop exit; the Snetterton HEAT 1 lap-1 contact between #5 and #899 shows cars tangled in the wet; at the Spa lap-25 contact between #22 and #418 the broadcast shows another part of the track.

Deviations, all made before the results were read and all because the pre-registered solver failed:

1. The first solver failed both check marks (the Oulton HEAT 1 offset at 131 s, the Cadwell HEAT 1 offset at 2927 s): it picked qualifying countdowns, whose lap counters share lap numbers with the race.
   It now checks that every LAP read, mapped through the offset, equals the feed's leader lap; drops lap reads that differ from both neighbours; and takes the point most lap edges cover.
2. A countdown split in two by a recurring digit misread is merged into the bigger cluster.
3. A heat and a feature at one track matched the same countdown, so sessions now take separate countdowns in race order.
4. A two-line track name ("Circuit de Spa- / Francorchamps") sets TIME and LAP 5 px lower, so the reader retries a band moved up 4 to 8 px for what it first missed; Spa went from 0 to 820 TIME reads.
5. Every change was made to pass a check mark, so the offsets are not a held-out test of the solver.
   The held-out evidence is the TIME witness.

Spa's countdown runs past an hour, which the reader cannot parse, so its first hour is aligned by LAP alone.

### Feed events

| Race, session | Gap collapses | with stall | with inc rise | with both | Inc rises (+4 or more) | Paired +4 pairs | Battles | Per-lap incident rows (placed in te) |
|---|---|---|---|---|---|---|---|---|
| Oulton HEAT 1 | 7 | 1 | 0 | 0 | 0 (0) | 0 | 23 | 51 (13) |
| Spa RACE | 76 | 20 | 28 | 5 | 224 (24) | 14 | 23 | 159 (148) |
| Snetterton HEAT 1 | 46 | 22 | 24 | 13 | 114 (13) | 5 | 16 | 52 (51) |
| Snetterton FEATURE | 31 | 12 | 11 | 5 | 83 (4) | 2 | 17 | 24 (24) |
| Brands Hatch HEAT 1 | 36 | 9 | 14 | 3 | 181 (16) | 13 | 65 | 35 (33) |
| Brands Hatch FEATURE | 56 | 15 | 30 | 13 | 155 (17) | 15 | 51 | 33 (32) |
| Donington RACE | 28 | 11 | 6 | 4 | 261 (4) | 1 | 64 | 84 (83) |
| Cadwell HEAT 1 | 45 | 12 | 16 | 7 | 185 (15) | 6 | 51 | 44 (44) |
| Cadwell FEATURE | 84 | 19 | 54 | 14 | 152 (24) | 15 | 42 | 48 (47) |
| Thruxton HEAT 1 | 26 | 5 | 8 | 5 | 80 (10) | 5 | 45 | 14 (14) |
| Thruxton FEATURE | 66 | 10 | 40 | 10 | 93 (21) | 24 | 61 | 15 (13) |
| **Total** | **501** | **136** | **231** | **79** | **1528 (148)** | **100** | **458** | **559 (502)** |

- No caution or non-green flag appears in any feed, so cautions cannot come from the feed.
- Paired +4 counts pairs, not W0-02's merged events, so Spa reads 14 here against W0-02's 12.
- The battle rule changed between feed versions, so battle counts do not compare across the older and newer races.
- The per-lap rows cover only drivers with the companion, 3 to 16 cars a session, and are placed in feed time by fitting lap durations (median fit error 2 s or less).

### Steward decisions joined

32 decisions: 19 on track, 8 incident totals, 3 qualifying, 1 conduct, 1 test row.

- 29 of 32 reach a race: 21 by the ruling text, 6 by the form fields, 2 by the race day alone.
  Decisions 2 and 21 fall on a two-race day and name neither race; 51 is a chat matter.
- Recorded conflicts: decision 5 (text race 2, form race 1), 11 (text Spa, form Oulton FEATURE), 26 (text races 6 and 7, form 7), 4 (text names Spa because of a Spa qualifying ban), 10 (filed after the next race day).
- The export is not quoted CSV: a field's line break is a carriage return plus a literal `\n`, so a standard CSV reader finds 100 rows; splitting on line feeds only finds 32 rows of 15 fields.

| Decision | Race | Cars | Lap | Contact candidate holding two named cars |
|---|---|---|---|---|
| 1 | Oulton HEAT 1 | 44, 111 | 1 | none (no counter on this feed) |
| 11 | Spa | 22, 418 | 25 | paired +4, stream 5289.5 to 5292.5 s |
| 13 | Spa | 26, 44 | 9 | collapse with stall or rise, stream 2889.5 s |
| 14 | Spa | 26, 70 | 2 | none: the victim named in the ruling is in #32 by decision 15 |
| 15 | Spa | 32, 70 | 2 | paired +4 and collapse, stream 2033.5 to 2036.5 s (W0-01's contact) |
| 16 | Snetterton HEAT 1 | 5, 18, 68 | 1 | none |
| 18 | Snetterton HEAT 1 | 5, 899 | 1 | collapse with stall or rise, stream 2337 s |
| 23 | Brands Hatch FEATURE | 12, 18, 899 | 27 | none |
| 24 | Brands Hatch FEATURE | 11, 12, 18, 899 | 27 | none (its paired +4s are with other cars) |
| 46 | Cadwell HEAT 1 | 01, 334, 899 | 1 | paired +4 #01 and #334, stream 1138.5 to 1141.5 s (hand mark 1141 to 1142) |

- **10 of 19 on-track decisions match feed events by car and lap, and 5 have a contact candidate holding two named cars, with stream seconds.**
- Not matched: 2 (race not named), 3, 4, 5 and 7 (no Oulton FEATURE feed), 6 (lap 22 is past the 7 laps of feed), 9 and 10 (no car number, no name match), 48 (Silverstone has no replay).
- Decision 46: the feed pairs #01 with #334 while the ruling penalises #899.
  The feed is a witness, not the ruling, and this is the case that shows it.

| Decision | Race | Stated total | Cars ending on exactly that total | Penalised car |
|---|---|---|---|---|
| 19 | Snetterton HEAT 1 | 21 | 18 | 18 (a match) |
| 20 | Snetterton HEAT 1 | 31 | 5 | none named |
| 21 | Snetterton, race not named | 27 | 91 (HEAT 1), none (FEATURE) | 7, absent from both feeds |
| 22 | Snetterton FEATURE | 24 | 418 | none named |
| 25 | Brands Hatch HEAT 1 | 30 | 26 | none named |
| 26 | Brands Hatch HEAT 1 and FEATURE | 25 and 22 | 5, then 5 and 418 | none named |
| 27 | Brands Hatch FEATURE | 21 | 84 | none named |
| 28 | Brands Hatch FEATURE | 22 | 5 and 418 | none named |

- 8 of 9 checks find a car on exactly the stated total, and the one with a named car (19) matches it.

### Repeatability

Every script ran twice; all ten output files hash the same across the two runs.
A check of every feed driver name against the catalogue file found none.

## What it shows

- **The broadcast-scan test bed exists**: 11 race sessions, seven streams, about 14.7 hours of video, each with a clock fixed to the feed at about ±2 s.
  A scan can run on a whole broadcast and be scored against the feed with no human label: the 100 paired +4 pairs and the 79 collapses with both a stall and a rise as recall targets, and the 213 collapses with neither, mostly passes, as a precision check.
- **A racing key not drafted by a model**: the sim's own incident counter and positions per second, the drivers' own per-lap counts, and 32 decisions written by stewards at the time.
  Five on-track rulings now have a feed contact with stream seconds, and the incident totals check 8 of 9 exactly.
- An offset says where a feed second sits in the stream, not that the camera shows it; at the Spa lap-25 contact it was elsewhere.
- A gap collapse is not a contact, and no collapse was checked against a frame beyond the three spot checks.
- The joins are text rules: where a decision has a conflict, the join is a reading, not a fact.

## Needs

1. The 75 per-driver telemetry files from the server, for Brock to pull, to replace the feed for those cars and rerun the event counts.
2. Brock's check on the update-rate claim, if he meant other races or another field.
3. Oulton FEATURE and the rest of Oulton HEAT 1; decisions 3, 4, 5 and 7 wait on them.
4. Replays for Silverstone and the second Donington race; decision 48 waits on Silverstone.
5. Decision 21: penalised #7 is in neither Snetterton feed, so Brock to say which race it was.
6. Camera-switch detection by frame difference, at $0, to measure how many contacts were ever on screen, which is a scan's real ceiling; it needs its own pre-registration.
7. A strip template for times past an hour, to give Spa's first hour a second witness.
