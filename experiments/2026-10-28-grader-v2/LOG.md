# Grader v2: a code-only score for the tournament's forklift candidates (28 and 29 Oct 2026)

Wave 1 built 16 faultline candidates from one brief.
They are `wild-01` to `wild-16`.
The first grader scored racing verdicts against model-drafted labels, which the design dropped.
Grader v2 scores the forklift side with code only: it runs each candidate's committed code and makes no model call of its own.

## Pre-registration (written and committed before any grader code)

### The graded set

- 26 synthetic fixed-camera forklift clips, the 16 of the smoke tests plus 10 from a second round, scored against a hand-checked key pinned by hash.
  If the key changes, the grader refuses until the pin is moved on purpose.
- A review of the key changed three labels: `no_spotter_04` breach to compliant, `reversing_spotter_05` compliant to a `pedestrian_separation` breach, and `separation_far_cctv_37` kept compliant.
- Each clip is given a neutral 7-character id, so no file name carries a draft label.
- The rules are the four graded rules of the `forklift-site-rules` pack, and the compile input is its four rule files joined in file-name order.
- Every input file's hash is written to a manifest.

| Subset | Clips | Use |
|---|---|---|
| Breach clips | 14 | breaches found |
| Compliant clips | 10 | false breaches |
| Speed clips | 2 | reported only: speed is not one of the four graded rules |

### Running a candidate

- Only committed code is graded; an uncommitted file never reaches the grader.
- `faultline judge` on the 26 items, `faultline replay` of its output with the network off, and `faultline compile` of the pack.
- `faultline scan --help` is checked for presence only; scan is never run or scored in wave 1.
- Walls: judge 1,800 s, replay 600 s, compile 900 s; a command past its wall counts as failed.
- Replay runs on the Windows host with every Python socket connect refused except loopback, which Python's event loop on Windows needs.
  This is weaker than `docker run --network none`, which stays the design's own mark for replay.

### Judge scoring

- A line is valid when it parses, its id is a graded item seen once, every ruling has a rule, a verdict (`breach`, `clear` or `unable_to_rule`), the missing fact when it is `unable_to_rule`, frame numbers and 40 to 600 characters of evidence, and its record is 64 lower-case hex characters.
  The same rule is held as a JSON Schema, and a test keeps the two in step.
- `valid_rate` is valid lines over 26.
- Several rulings on one graded rule in a line resolve strictly: breach if any says breach, else `unable_to_rule` if any says so, else clear.
- `breaches_found`: breach clips with a breach on the key rule or a rule the key also allows, out of 14.
- `false_breaches`: compliant clips with a breach on any of the four graded rules, out of 10, counted once a clip.
- `unable_to_rule`: graded rulings with that verdict, out of 96 (24 clips, four rules).
- Reported, not ranked: breaches on a rule the key does not name, because the key names one rule per breach clip and is silent on the other three.
- `replay_pass`: judge and replay both exit 0 and the two prediction files hash the same.

### Compile scoring

- `parsed`: pack rules with a matching object whose route is `scan`, `window` or `out`, naming at least one field unless the route is `out`, out of 4.
- `invented`: field references outside the brief's 15-field vocabulary (for example `truck.reversing`, `person.distance_m`, `contact.consequence`); `site.<name>` references are site values, never invented.
- `bare_literals`: numbers in a rule object with neither the words they came from (`span`) nor a site value beside them.

### The rank

A wrong pass is worse than a wrong fail, so false breaches dominate.

1. Gate: `valid_rate` of 0.9 or more; a candidate under the gate sorts below every one that passes it.
2. False breaches, fewest first.
3. Breaches found, most first.
4. Replay pass first.
5. Compile: parse rate highest, then invented fewest, then bare literals fewest.
6. Candidate id, so ties sort the same way every time.

A candidate that rules every clip `unable_to_rule` scores 0 false breaches and 0 found, so it ranks under any candidate with 0 false breaches and one breach found.
That is intended: refusing is safer than a false breach, and finding is the tie-break.

The score files and leaderboard carry no clock time, so two grades of the same commit with the same judge output are byte-identical.

### Pass marks for the grader itself

- A stub candidate written to the contract, graded twice, gives byte-identical score files and leaderboard.
- The stub's scores match a hand count of its table.
- Each rule is shown red by mutation.
- No paid call is made by the tests or the stub.

## Checking the grader (28 Oct, $0)

Every pass mark met, on the real 26 clips.

| Candidate | Gate | False breaches | Found | Unable | Invalid | Replay | Compile | Hand count |
|---|---|---|---|---|---|---|---|---|
| stub-b (refuses all) | pass | 0/10 | 0/14 | 96 | 0 | pass | 4/4, 0 invented, 0 bare | matches |
| stub-a (mixed table) | pass | 2/10 | 11/14 | 3 | 0 | pass | 4/4, 1 invented, 1 bare | matches |
| prompt-only baseline | fail | 0/10 | 0/14 | 0 | 26 | fail | 0/4 | no `faultline` command |

- The stub's replay makes one outbound call on purpose, and the guard blocked it.
- Two full grades of both stubs gave byte-identical score files and leaderboard.
- Nine source mutations each turned at least one test red: a false breach not counted, a duplicate id accepted, any verdict accepted, invented fields ignored, bare literals ignored, the gate ignored, the key review skipped, the allowed rules dropped, and a one-byte replay drift with the guard off.
- Deviation: the key pin is the hash of the key's canonical JSON, not of the file bytes, so a line-ending change never trips it while any content change does.
- That evening, on my decision, the key file itself took the three reviewed labels and the grader's own override was removed.
  The stub scores did not move, and two grades were still byte-identical.

## Wave 1 (29 Oct)

The first scores were wrong: judge and compile spent from each candidate's own $1 cap, most of which were already spent, and every failed call counted as an invalid line.
The fix gives the grader its own cap, $0.75 a candidate; an invalid line now means one that breaks the schema, and an id with no line is counted apart as missing.
The ranking rule is unchanged.
All 16 were graded again at their collected commits, on my word.

| # | Candidate | Gate | False breaches | Found | Unable | Invalid | Missing | Replay | Compile | Invented | Bare |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | wild-07 | pass | 0/10 | 3/14 | 75 | 0 | 0 | pass | 4/4 | 0 | 6 |
| 2 | wild-13 | pass | 0/10 | 3/14 | 62 | 0 | 0 | pass | 1/4 | 0 | 1 |
| 3 | wild-11 | pass | 0/10 | 3/14 | 72 | 0 | 0 | pass | 0/4 | 0 | 0 |
| 4 | wild-01 | pass | 0/10 | 0/14 | 0 | 0 | 0 | fail | 0/4 | 0 | 0 |
| 5 | wild-09 | pass | 1/10 | 9/14 | 13 | 0 | 0 | pass | 4/4 | 0 | 1 |
| 6 | wild-03 | pass | 2/10 | 12/14 | 6 | 0 | 0 | pass | 1/4 | 0 | 0 |
| 7 | wild-12 | pass | 2/10 | 10/14 | 14 | 0 | 0 | pass | 1/4 | 0 | 1 |
| 8 to 16 | wild-05, 06, 15, 16, 04, 02, 08, 10, 14 | fail | | | | | | | | | |

- Nine candidates fail the gate.
  wild-05 and wild-06 write a record that is not 64 lower-case hex on every line; the other seven crash in judge before writing a line.
- Three of the seven (wild-04, 14, 15) read a compiled predicates file from the rules folder, which the contract passes as markdown rules only.
- Four (wild-02, 08, 10, 16) look up a floor plane or camera by the smoke tests' clip names or mark files, and the grader gives neutral names and a site file with no camera or plane.
  These are candidate faults under the contract as written, and also a gap in the brief: a judge that measures distance needs the floor plane from somewhere, and the next brief should say where.

## What it shows

- The pre-registered order puts false breaches first, so a cautious judge that rules almost everything `unable_to_rule` ranks above one that finds most breaches.
  The top three find 3 of 14 and leave 62 to 75 of 96 rulings unable.
- wild-01 ranks fourth with 0 found: it rules every clip clear, and its replay fails.
- wild-03 (12 of 14 found, 2 false) and wild-09 (9 of 14 found, 1 false, compile 4 of 4, replay pass) are the strongest judges on recall.
- The rule stays as registered; it rewards abstention, which is for me to weigh before wave 2.

## Spend

The grader spent $1.50 across 13 candidates; the other three crashed before any call.
The most one candidate spent was $0.45, and no call hit the $0.75 cap.
The top five have not yet been reviewed on these scores.

## What this does not prove

- The replay guard fences Python sockets only; a native binary a candidate shells out to is not fenced.
- Compile can be satisfied by routing every rule `out` (stub-b scores 4 of 4), so the parse rate alone means little; it is the last tie-break, and such a candidate finds no breaches.
- Requests a candidate already made come from the shared cache at no cost, but SAM is not deterministic, so a re-judge may miss the cache.
