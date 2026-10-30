# Racing pipeline: one judge from the pieces that each worked alone (29 Oct 2026)

A steward protest goes in.
Scripts find the second and lap in the companion feed, confirm contact from the sim's own paired +4 count, and close the set of cars that could be involved.
Frames from that second come out of the broadcast through the measured stream offset.
A Meta model gives its read of fault under the league's rules pack, choosing the offender only from the closed set.
Beside it, the incident-limit rule (league code 9.2) rules from data alone.
The league is a PitBot league; its name, its drivers' names and its stream ids stay out of this repo.
Car numbers, track names and decision ids only.

## Pre-registration (written and committed before any score is computed)

### Question

The 29 Oct telemetry test tried one piece alone: the paired +4 count with a "car behind" guess covered 2 of 9 decisions and named 0 of 3 offenders.
This build tests the pieces together, which no run has done yet.

### Inputs

- The companion replay feeds for 11 race sessions across 7 race days: Oulton HEAT 1, Spa RACE, Snetterton HEAT 1 and FEATURE, Brands Hatch HEAT 1 and FEATURE, Donington RACE, Cadwell HEAT 1 and FEATURE, Thruxton HEAT 1 and FEATURE.
- The 7 broadcast streams of those races, with the stream offset per session fixed by the 28 Oct catalogue at ±2 s (±4 s for Brands Hatch HEAT 1).
- The league's steward decisions export: 32 decisions, of which 19 are on track.
- The league's rules pack, rule `S21`, which holds all of section 9 (9.2 incident limits, 9.5 penalty guide, 9.9 only reported incidents are ruled).
- The 27 Oct answer key: the contact second and the roles for 12 reports, read from the feed and the ruling texts.
- A private prep script, `scripts/racing_prep.py`, reads these in place and writes the private inputs this run uses: the session table, one protest per decision with report fields only, and a draft truth table.
  The protests carry no verdict, no ruling text, no penalised driver or car, and no evidence link.
- Two runs of the prep script give byte-identical files.

### The ten decisions

- Ten on-track decisions run through the judge: 1, 11, 13, 14, 15, 16, 18, 23, 24 and 46.
- They were chosen because they already match feed events by car and lap in the 28 Oct catalogue.
  That choice flatters the locator: a protest with no feed event never reaches its score.
- The 9 on-track decisions with no feed match (2, 3, 4, 5, 6, 7, 9, 10 and 48) run too, are expected to refuse, and are counted here.
- Decision 1 is on Oulton HEAT 1, whose feed shows no incident counter for any car.
  It stays in, and the truth table marks it "no counter".

### Identity

- A car is its sim number inside the feed, its sim customer id (`custId`), and its league number.
- The league number of a `custId` is the number it ran in Season 1; a `custId` first seen in Season 2 keeps its first Season 2 number.
- Numbers are reused by different drivers across sessions, so a written number resolves inside one session.
- Decision 46 is the test: league #899 ran as sim #01 at Cadwell, the same `custId`.

### Truth

- Three sources sit side by side for each decision: the catalogue's penalised car, the answer key joined by session, lap and cars (never by id), and the decisions file's penalised driver resolved to a car number in memory.
- Every disagreement is a conflict row for me to settle, never resolved by code.
- Nothing is scored until I have confirmed the table.
- A truth contact second exists only where the answer key gives one: decisions 1, 11, 13, 15, 16, 23 and 46, so n is 7 for the locator.
  Decisions 14, 18 and 24 are reported and not scored for the locator.
- Answer key report 23 (car 12 on car 18, lap 27) matches both decision 23 and decision 24 by session, lap and cars.
  The prep script attaches it to neither and lists both assignments for me, so the draft holds 6 contact seconds until I rule.
  The locator's 7 assumes I give that key row to decision 23.

### The pipeline

1. Normalise the protest: every car number and driver name becomes `car <sim number>`; outcome words are redacted; a leak lint checks the text.
2. Locate: inside the stated lap ±1, pick the feed event that holds a protest car (paired +4 first, then a gap collapse with a stall and an incident rise, then a collapse with either, then an incident rise of 2 or more), and pad its seconds 3 s before and 2 s after.
3. Close the set: every car within 8 m of a protest car over the window, ±3 s.
4. Facts: blame-neutral sentences from the feed (registered contact pair, off-track and loss-of-control counts, stall seconds, order before contact), each with its time resolution and the fixed sentence "no registered contact does not mean no contact".
5. Frames: 2 a second over 4 s either side of the contact second in the stream, masked where the broadcast shows names, hashed, metadata stripped.
6. The model's read: the pack's rule text, the facts, the closed set, the normalised protest and the frames; the offender must come from the closed set; three runs, and a read counts only when all three agree.
7. Incident limit, beside it: a car breaches when its last shown counter is over the session's limit (20 on a two-race day, 25 on a one-race day).
8. Record and replay: every ruling carries its rule, offender, frames, evidence and a record hash, and rebuilds byte-identically with the network off.

For a contact, the script never rules a breach.
It sends the window, the closed set, the facts and the frames to the steward, and the model's read sits beside them.

### Pass marks (fixed here, never lowered)

1. Rule A, incident limit (a drift check, not new evidence: it must reproduce the 29 Oct result): 7 of 7 incident-total decisions found (19, 20, 22, 25, 26, 27, 28), breaching cars with no decision listed as "not ruled" under 9.9, byte-identical over two runs.
2. Locator: the window holds the key's `closest_te` ±2 s on at least 5 of the 7 decisions with a truth second (1, 11, 13, 15, 16, 23, 46). Decisions 14, 18 and 24 are reported, unscored. The 10 were chosen because they already match feed events, which flatters the locator: say so in the LOG. The 9 on-track decisions with no feed match (2, 3, 4, 5, 6, 7, 9, 10, 48) run too and are expected to refuse, and the LOG counts them.
3. Closed set: every truth party (offender and victim, through the number map) is inside the candidate set on at least 7 of the 10, median set size 4 or fewer. Rule B alone scored 2 of 9 (decision 1 left out there): show both denominators side by side.
4. Model's read, offender: n is the count of decisions with an offender I confirmed. The mark is fixed in this section after the two constants are computed in `racing_prep.py` and before any model call: an agreed read names the truth offender on more decisions than the better constant. If the better constant already scores n of n, mark 4 is "equal to it with every read agreed", and the LOG says the constant is hard to beat. No agreed read counts as not right.
5. Model's read, verdict: reported only, no mark, because the constant "penalty" already scores most rows.
6. Replay: `faultline replay` rebuilds preds byte-identical with the network blocked, on two runs.
7. Spend: at most $5 on the d0 proxy for this build.

### Mark 4, made concrete

The two offender constants, computed at $0 by the prep script before any model call:

- **Car behind**: at the last feed frame at or before the truth contact second minus 1 s, take the two closest of the protest's cars (reporter, involved, numbers and names in the description; a lone car is paired with its nearest car on track), and name the one later in track order.
  It uses the answer key's contact second, so it is stronger than any guess the judge could make before locating.
  A decision with no truth contact second gets no guess.
- **Accused**: the first car named in the protest's `involved` field that is not the reporter's car.
  `involved` is empty on 6 of the 10 protests (1, 11, 13, 14, 15, 18) and names only the reporter's own car on 1 more (16), so it says nothing on 7 of the 10.

On the draft truth table, before my confirmation:

| Constant | Right | n |
|---|---|---|
| Car behind | 5 | 5 |
| Accused | 1 | 5 |

- n is 5: the decisions whose draft offender has no open conflict (1, 11, 13, 16, 46).
  Decisions 23 and 24 are out until I say which of them answer key report 23 belongs to.
- The better constant is the car behind, at 5 of 5.
- **Mark 4 on the draft: the better constant already scores 5 of 5, so mark 4 is "equal to it with every read agreed": an agreed read names the truth offender on all 5 of 5 decisions.**
- The car-behind constant is hard to beat: it already names every draft offender, because it is given the answer key's contact second.
- When I confirm the table, the prep script rebuilds both constants from it, recomputing the car-behind guess at each confirmed contact second.
  This pre-registration is not edited after its commit.
  The confirmed n and the constants' scores land in a separate "Mark 4 on the confirmed table" section, in its own commit, after the pre-registration commit and before any model call.
  The rule stays as worded above; only n and the constant's count follow the confirmed table.

### Decisions I answered at plan time (29 Oct), recorded rather than re-asked

The approved design brief is followed except in four places:

1. Model: Spark Open gives the read, as the brief says.
   Spark 1.3 is the pre-registered fallback arm, used only if Spark Open fails mark 4 or more than a third of its runs fail to parse.
2. Car and lap: scripts read them from the feed, not a vision model.
   I agreed on one condition: the core stays one piece for every setting, so the "who and when" facts come from an adapter (the racing feed here, vision for forklift sites later) and the core never knows which.
3. Public numbers: the README may quote this build's scores, with car numbers only and the league unnamed.
4. Forklift: out of this build, in its own plan after this one.

The cars over the incident limit with no decision on record are a headline output, not a footnote.
The judge flags them for the stewards.
This LOG, the README and the cards call them "over the limit, no ruling on record", never a breach the stewards missed.
Under code 9.9 only reported incidents are ruled, and only the stewards can say why no ruling exists.

### Limits known before the run

- The ten decisions were picked because the feed already holds an event for them, so the locator score is an upper bound for protests in general.
- The truth contact second comes from one source, the answer key, on 7 decisions.
- Oulton and Snetterton feeds write a frame about every 2 s, so their timing is 2 s, not 1 s.
- An offset says where a feed second sits in the stream, not that the broadcast camera shows it.
  At the Spa lap-25 contact the camera was elsewhere.

## Truth confirmed, and Mark 4 on the confirmed table (29 Oct, before any model call)

This section is added after the pre-registration and before any score or model call.
The pre-registration above is not edited; the rule for mark 4 is applied as worded there.

### The confirmed truth

The truth calls come from a frame check of the broadcast on 29 Oct.
Every row below is recorded as confirmed by me on that basis.
Car numbers are sim numbers in the session.

| Decision | Session | Offender | Victim | Contact second (te) | Source of the second | Scored as |
|---|---|---|---|---|---|---|
| 1 | Oulton HEAT 1 | 44 | 111 | 175 | answer key | itself |
| 11 | Spa RACE | 418 | 22 | 3787 | answer key | itself |
| 13 | Spa RACE | 44 | 26 | 1387 | answer key | itself |
| 14 | Spa RACE | 70 | 32 | 533 | answer key | duplicate of 15 |
| 15 | Spa RACE | 70 | 32 | 533 | answer key | itself |
| 16 | Snetterton HEAT 1 | 68 | 18 | 299 | answer key | itself |
| 18 | Snetterton HEAT 1 | 5 | 899 | none | none | itself, offender only |
| 23 | Brands Hatch FEATURE | 12 | 18 | 2471 | video | duplicate of 24 |
| 24 | Brands Hatch FEATURE | 12 | 18 | 2471 | video | itself |
| 46 | Cadwell HEAT 1 | 01 (league #899) | 334 | 162 | answer key | itself |

- Every verdict is penalty.
  Decision 15 is filed as no action, but its ruling text is an appeal reply saying the earlier decision on car 70 stands, so its truth verdict is penalty.
- Decision 11 is the Spa race, as its ruling text says; its form fields named another race.
- Two pairs are one incident each, and each pair is scored once, through its primary:
  - 14 and 15: car 70 outbraking into the Bus Stop on lap 2 and hitting car 32. Primary 15.
  - 23 and 24: both carry the same ruling text, and both verdict lines penalise car 12; decision 23's own penalised field contradicts its text. Primary 24.
- Decision 24's contact second is corrected from the video: the frames show car 12 hitting car 18 at te 2471, the feed has car 18 stalling at 2471, and the answer key's 2467 is 4 to 5 s early.
- Decision 16: the frames show car 68 alongside and car 18 spun; the other driver named in the verdict line is a copy slip.
- Decision 18: the ruling resolves to car 5; the #58 it also mentions is not in the session.
  It has no contact second, so it is scored for the offender and not for the locator.

### Mark 2's scored set

- The locator is scored on 1, 11, 13, 15, 16, 24 and 46, still 7 decisions.
- Decision 24 takes the place of 23 in the set the pass mark lists, because the two rows are one incident; the incident's second is te 2471 from the video, not the answer key's 2467.
- Decisions 14 and 23 are reported as duplicates and not scored, and 18 has no second.

### A fifth deviation: the race is given, not found

- My call on 29 Oct: a real steward always knows which race a protest is about.
- Each protest line now carries its session as an input, beside the report fields.
- The judge is told the race and finds the second and the cars inside it; finding the race is not part of what is scored.
- The 9 no-feed protests carry the catalogue's session where it names one (7 of 9), and none for decisions 2 and 48.

### Mark 4 on the confirmed table

The prep script rebuilt both constants from the confirmed table, recomputing the car-behind guess at each confirmed contact second, with the duplicates 14 and 23 left out.

| Constant | Right | n |
|---|---|---|
| Car behind | 7 | 8 |
| Accused | 2 | 8 |

- n is 8: decisions 1, 11, 13, 15, 16, 18, 24 and 46.
- The better constant is the car behind, at 7 of 8.
  Its one miss is decision 18, which has no contact second and so gets no guess.
- The accused constant names the offender on 24 and 46 only.
- **Mark 4: an agreed read names the truth offender on more than 7 of 8 decisions, which means 8 of 8.**
- The car-behind constant is hard to beat: it is handed the confirmed contact second, which the judge has to find for itself.
- The truth contact second now comes from the answer key on 6 scored decisions and from the video on 1 (decision 24).
- The car-behind constant uses the answer key's contact second, and the key's offenders were read partly from the same feed, so its 5 of 5 may be partly circular.

## Fixed during the build, before any score (29 to 30 Oct)

These three points were settled while the adapter was built and reviewed, before the locator or the closed set had been scored.
They are written here, in their own commit, before the first score.

### Locator scope

- An event is in scope when its lap span overlaps the stated lap ±1.
- An event's lap span runs from the lowest to the highest of the leader's lap and each protest car's own lap, read at the event's start and end.
- The first build tested only the laps at the event's two ends, so an event spanning the stated lap could be missed.
  An incident rise whose counter was hidden for a while can span leader laps 5 to 9, and it is in scope for "lap 7".

### Gap collapses: 504, not the catalogue's 501

- The paired +4 count matches the 28 Oct catalogue exactly: 100 across the 11 sessions.
- The collapse count is 504 against the catalogue's 501.
- The catalogue looks back 3 feed lines, and the pre-registered rule says 3 seconds.
  Where the feed repeats a second, 3 lines span less than 3 seconds, and the catalogue misses 3 collapses.
- This build keeps the pre-registered 3 seconds.
  The drift test asserts the catalogue's 501 are all found, plus exactly these 3.

### What the protest normaliser resolves

- A lone lower-case word that matches part of a driver's name becomes `[unresolved driver]` rather than refusing the whole protest (protests 23 and 24).
- Protest 15 names a driver by a first name that another person in the league also holds, so it resolves no named car.
  Its locator input is the reporter's car alone.
- Protests 16 and 18 name drivers in full, and both resolve.

### How marks 2 and 3 treat a refusal (30 Oct, from the scorer's review)

- A refused protest is a miss for marks 2 and 3, even when the locator found a window before the refusal.
- Mark 3's median has two readings, because a refused protest has no set.
  The mark passes only when both are 4 or fewer: the median over all 10 with a refusal counted as size 0, and the median over the located protests only.
- Mark 2 prints each window's width beside it, so a wide window that holds the truth second by its width alone shows.

## Results

### Checkpoint 3, the $0 score (30 Oct)

Decision 18's victim stays car 899 alone, as confirmed, settled before this score was computed.
The incident-limit run and the locate run were each run twice, and each pair is byte-identical.
`faultline replay` rebuilt both files byte-identically from their records.

| Mark | Result | Pass mark | Verdict |
|---|---|---|---|
| 1, incident limit | 7 of 7 decisions found | 7 of 7 | pass |
| 2, locator | 2 of 7 windows hold the truth second ±2 s | 5 of 7 | **fail** |
| 3, closed set | truth parties inside on 9 of 10, median size 3 (3 over the 9 located) | 7 of 10, median 4 or fewer | pass |

- Mark 2 with no tolerance at all also gives 2 of 7.
- The 9 protests with no feed match all refused, as expected: 4 have no feed for their session, 2 name no session, 2 name no car, and 1 holds no feed event with a protest car.
- Beside rule B: rule B's closed read covered 2 of 9; this build's closed set holds the parties on 9 of 10, and 9 of 9 without decision 1.

### Why mark 3 passes and what it does not show

- The closed set is built around the protest's own cars, so a car the protest names is always a candidate once a window exists.
- On all 9 located decisions, both truth parties are cars the protest names.
- Mark 3 therefore shows that the protest names the right cars and that the window was found, not that the window is the right moment.
- Rule B had no protest to read, so its 2 of 9 is not a like-for-like comparison.

### Where the locator went wrong, per decision

| Decision | Truth second | Window | What the locator picked | What the feed holds at the truth second |
|---|---|---|---|---|
| 1 | 175 | refused | no event: Oulton HEAT 1 shows no incident counter | no event |
| 11 | 3787 | 3784 to 3792 | held | |
| 13 | 1387 | 1217 to 1257 | a paired +4 on the lap before, holding one protest car (44) | a gap collapse with an incident rise holding both protest cars, 26 and 44, at 1387 |
| 15 | 533 | 286 to 336 | an earlier paired +4 between the same two cars, 32 and 70, on leader lap 1 | a second paired +4 between 32 and 70 at 531 to 534, on leader lap 3 |
| 16 | 299 | 279 to 284 | a gap collapse at 282, holding car 68 | no event at 299 holds car 68 or car 18, other than a long incident rise on 68 from 244 to 322 |
| 24 | 2471 | 2241 to 2252 | the first paired +4 in the session holding two protest cars (18 and 899) | the protest states no lap, so the whole race was searched |
| 46 | 162 | 159 to 167 | held | |

- On decision 13, the pre-registered order ranks the kind of event above the number of protest cars it holds.
- On decision 15, both events hold the same two cars and both sit inside the stated lap ±1, and the tie goes to the earlier one.
- On decision 16, the feed holds no event at the truth second; Snetterton writes a frame about every 2 s.
- On decision 24, with no lap stated, the earliest event holding protest cars wins across the whole race.
- The order and the tie-break are pre-registered, and they are not changed after this score.

### Over the limit, no ruling on record

Under code 9.9 only reported incidents are ruled, and only the stewards can say why no ruling exists.

| Track | Session | Car | Total | Limit | Clause |
|---|---|---|---|---|---|
| Spa | RACE | 26 | 29 | 25 | 9.2.2 |
| Spa | RACE | 70 | 30 | 25 | 9.2.2 |
| Snetterton | HEAT 1 | 91 | 27 | 20 | 9.2.1 |
| Donington | RACE | 5 | 27 | 25 | 9.2.2 |
| Donington | RACE | 12 | 29 | 25 | 9.2.2 |
| Donington | RACE | 18 | 27 | 25 | 9.2.2 |
| Donington | RACE | 19 | 30 | 25 | 9.2.2 |
| Donington | RACE | 69 | 27 | 25 | 9.2.2 |
| Donington | RACE | 418 | 29 | 25 | 9.2.2 |
| Cadwell | HEAT 1 | 01 | 24 | 20 | 9.2.1 |
| Cadwell | HEAT 1 | 18 | 29 | 20 | 9.2.1 |
| Cadwell | HEAT 1 | 19 | 25 | 20 | 9.2.1 |
| Cadwell | HEAT 1 | 44 | 21 | 20 | 9.2.1 |
| Cadwell | HEAT 1 | 334 | 22 | 20 | 9.2.1 |
| Cadwell | FEATURE | 19 | 25 | 20 | 9.2.1 |
| Cadwell | FEATURE | 44 | 21 | 20 | 9.2.1 |
| Cadwell | FEATURE | 84 | 28 | 20 | 9.2.1 |
| Cadwell | FEATURE | 123 | 27 | 20 | 9.2.1 |
| Thruxton | FEATURE | 19 | 23 | 20 | 9.2.1 |
| Thruxton | FEATURE | 57 | 22 | 20 | 9.2.1 |
| Thruxton | FEATURE | 84 | 25 | 20 | 9.2.1 |

The run found 29 cars over the limit: 8 match a ruling on record and 21 have none.
Oulton HEAT 1 shows no counter, so it is not ruled.

## A sixth deviation: the steward gives the moment (30 Oct, after the locator failed, before any frame is cut)

- My call on 30 Oct, after the locator scored 2 of 7: the steward gives the moment, as a steward reviewing a protest does.
- Each protest gets one feed second as an input beside the report: the confirmed contact second from the truth table, the same second the car-behind constant is handed.
- Decision 18 has no truth contact second.
  Its moment is te 322 (stream 39:45), where the 30 Oct frame check placed the lap 1 turn 4 pile-up, and the Checkpoint 4 frame look confirms or rejects it.
- Duplicates 14 and 23 take their primary's second.
- From this point the window, the closed set, the facts and the frames are built around that second: 3 s before to 2 s after for the window, 4 s either side for the frames.
- The locator still runs, its window is kept in each record, and its 2 of 7 stands as its own result.
- Mark 4 is now a fair test of the model's read against the car-behind constant, because both are handed the same second.
- Mark 4's rule, its n of 8 and its pass at 8 of 8 are unchanged.

### Checkpoint 4, frames and the offline dry run (30 Oct, $0)

- Each located protest gets 17 frames, 2 a second over 4 s either side of the steward's moment.
- Two frame runs are byte-identical, and every frame file is named by its own hash.
- JPEG bytes can differ between ffmpeg builds.
  The record hashes the frames this machine produced, and the replay checks those hashes and never re-encodes.
- A model run with a fixed fake reply, through the full rule stage, gives byte-identical output on two runs, and the second run sends nothing.
- `faultline replay` rebuilt both fake runs byte-identically with the network blocked and the proxy ports closed; the guard logged 0 connection attempts.

#### What the frames hide

A look at one frame per stream, then at every frame of every located protest, found three things the first masks missed:

- The league's logo sits top left on every stream, and is now covered with the timing strip beside it.
- A fastest-lap banner at the top of the Spa stream names a driver, and is now covered.
- Two other broadcast layouts appear: two stacked camera panes, and a picture-in-picture view.
  Both carry driver name cards that move with the layout.

Fixed masks cannot follow a moving layout, so a frame in either layout is dropped, with one frame either side to catch the cross-fade.
The layout is found from the orange pane borders, by pixel probes on the picture before the masks are drawn.
On these protests, only decision 16 lost frames: 2 of 17.
No kept frame shows a driver name.
One neighbour each side covers 0.5 s of cross-fade; a slower fade could leave a faint card in the next frame, so every frame set is still looked at before it is sent.
The model's written reason passes the same name check as the prompt, so a name it read from a missed card counts as a failed run.

#### The frame look, per protest

This is a look, not a score.

| Decision | What the frames show around the moment |
|---|---|
| 1 | A line of cars, then a car alongside; no clear contact |
| 11 | Two cars close together through a bend |
| 13 | A pack through the first corner; contact not clear at this camera |
| 15 | A high wide shot of a group through the chicane; the cars are small |
| 16 | The contact: debris and a spun car |
| 18 | Heavy spray, then cars side by side after the pile-up; the contact itself is not clearly in frame |
| 24 | A group at the hairpin, with smoke |
| 46 | A pack, then smoke and a car off the track |

- The camera shows the contact clearly on 1 of 8 scored protests, and the aftermath on 3 more.
- The `not_visible` verdict exists for exactly this, and the model may use it.

## A seventh deviation: 8 frames a call, the 8 scored protests, and the honesty card on 18 (30 Oct, before any model call)

- Arm 1's model is served by a host that refuses more than 8 images in one request.
- The cut stays 17 frames a protest, and every one stays on the ruling line as evidence.
- Each model call takes 8 of them: the frame nearest each whole second from 4 s before the moment to 3 s after, within 0.5 s, the earlier one on a tie.
- A protest with dropped frames may send fewer than 8.
- Both arms send the same 8 frames, so the two arms differ only in the model and the reply form.
- Only the 8 scored protests are sent (1, 11, 13, 15, 16, 18, 24, 46).
- Duplicates 14 and 23 would send their primary's moment and frames again, so they are not sent.
- The honesty card planned on 14 or 24 cannot fire, because the moment gives every scored protest a window and no scored protest is refused.
- The card moves to decision 18, where the frame look found the contact not clearly in frame.
- The card sets the model's read on 18 beside that look: a `not_visible` read is the honest answer, and a named offender is a read of something the frames do not show.
- No extra calls are made for the card.
- Mark 4, its n of 8 and its pass at 8 of 8 are unchanged.
- Spend: 24 calls an arm, arm 2 only under the rule already written, an upper estimate of $3.60 for both arms, inside the $5 line.

## Fixed after arm 1's replies came back, before any score (30 Oct)

- Arm 1 made 24 calls for $1.11, with no cached reply.
- Six runs used the whole 12,000-token ceiling on reasoning and returned no text: those runs stay failed.
- Seventeen replies were marked as lint hits, and every hit was a slash the path check reads as a file path ("5.6m/s", "9.5/9.5.2", "green/blue").
- None of the 17 held a name.
- This LOG's rule for the reply is a name check ("What the frames hide"), and the code ran the whole prompt lint instead.
- The reply check now refuses names, emails, handles and URLs only, as this LOG says, and the stored replies are judged again from the ledger at $0.
- No prompt changed, no call was repeated, and the arm 2 rule is unchanged.
- I read the reply endings to find the cause, before any score was computed.

## Checkpoint 5, the model's read (30 Oct, paid)

Both arms ran, under the arm 2 rule written before any call: arm 1 cannot pass mark 4 with 4 agreed reads of 8.
Each arm made 24 calls, 3 runs on each of the 8 scored protests, with no cached reply.
Each call sent 8 frames, except decision 16, which sent 7 because its cut has dropped frames.

| Decision | Track | Cars in the set | Truth offender | Arm 1 read (Spark Open) | Arm 2 read (Spark 1.3) |
|---|---|---|---|---|---|
| 1 | Oulton Park | 12, 18, 44, 111 | 44 | runs disagree | runs disagree |
| 11 | Spa | 22, 418 | 418 | no text, 3 of 3 runs | runs disagree |
| 13 | Spa | 12, 26, 44, 899 | 44 | penalty, 44 | penalty, 44 |
| 15 | Spa | 12, 32, 70 | 70 | penalty, 70 | penalty, 70 |
| 16 | Snetterton | 16, 18, 19, 37, 68 | 68 | penalty, 68 | penalty, 68 |
| 18 | Snetterton | 5, 899 | 5 | runs disagree | not visible |
| 24 | Brands Hatch | 11, 12, 18, 68, 899 | 12 | no text, 3 of 3 runs | runs disagree |
| 46 | Cadwell Park | 01, 18, 44, 334 | 01 | penalty, 01 | penalty, 01 |

### The marks

- Mark 4, offender: 4 of 8 on each arm, against a pass of 8 of 8.
- Mark 4 fails on both arms.
- The car-behind constant scores 7 of 8.
- Every agreed read that named a car named the truth offender: 4 of 4 on each arm.
- Single runs did name a wrong car, and the agreement gate kept each one out.
- On arm 2, one run on decision 11 named car 22, the car the truth table holds as the victim.
- On arm 2, one run on decision 1 named car 44 beside two `not_visible` runs, so that read did not agree.
- Mark 5, verdict (reported, no mark): 4 of 8 match the truth verdict on each arm.
- Arm 1 agreed on 4 reads and arm 2 on 5.
- Mark 6, replay: both arms ran a second time from the ledger with the network blocked and wrote byte-identical files.
- `faultline replay` rebuilt both files byte-identically.
- Mark 7, spend: $1.76 on the metering proxy (arm 1 $1.11, arm 2 $0.66), inside the $5 line.
- Arm 1 returned no text on 6 of 24 runs, all on decisions 11 and 24, because its reasoning used the whole 12,000-token ceiling.
- That is 1 run in 4, under the arm 2 rule's one third.
- Arm 2 returned valid replies on 24 of 24 runs.
- Mark 2 rerun at this stage scores the window built around the steward's moment, so it holds 7 of 7 by construction.
- The locator's own result is still 2 of 7 (Checkpoint 3).
- Mark 3 at this stage is 8 of 10, median set size 3.5 over all 10 and 4 over the 8 located.

### Fixed in the scorer before the scores were written

- The scorer labelled an agreed read with no offender as "offender outside candidates", because a null offender is not in the set.
- That label was false, since the read named no car.
- The fix keeps such a read as agreed, never right on mark 4, and counted on mark 5.
- It changed one row: arm 2's agreed `not_visible` read on decision 18.
- Neither numerator changed: mark 4 stays 4 of 8 and mark 5 stays 4 of 8 on both arms.
- Both score files were written after the fix.

### The honesty card, decision 18

- At decision 18's moment, the frame look found spray and then the cars after the pile-up, with the contact itself not clearly in frame.
- Arm 2 agreed on all three runs that the contact is not visible, and named no car.
- Arm 1's three runs disagreed: two said `not_visible` and one named car 5 for a penalty.
- That one run read something the frames do not show, and the agreement gate kept it out of the read.
- The steward's ruling names car 5.
- No agreed read claimed to see what the frames do not show.

### What the demo shows

- The model's read fails mark 4 on both arms, so the demo shows the evidence pack and the steward's ruling without the model's read, as the design allows.
- The evidence cards still list each read as "the model's read", with this result beside it, and never as a ruling.
- Any change to chase the mark is a new arm in a new section, written before its first call.
