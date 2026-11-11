# Smoke test A: closed-set identity (27 Oct 2026)

Piece 1 of the deterministic-reads design, a private note not in this repo. Scripts only, no model, no paid call, $0.
The script `smoke_a.py` writes `results.json`; both stay with the private tooling.

## Method

- Camera car: the reporter, else the victim.
- Contact second: the key's `closest` second. Reports 10 and 18 have none, so their window midpoint is used and they are not scored.
- Set: every car within 8 m along the track of the camera car at that second, and over the second ± 3 s (`telem.Replay.gap_m`, Companion 1 Hz replay).
- Snap: a read number goes to the candidate with the smallest digit edit distance. A tie or a distance over 1 returns nothing.
- Single-partner rule: exactly one car within 3 m at the contact second.

## Result

| Measure | Result |
|---|---|
| Key partner inside the set, at the contact second | 10 of 10 scoreable |
| Key partner inside the set, ± 3 s | 10 of 10 scoreable |
| Median set size, at the second / ± 3 s | 1 / 2 (largest: report 16, 4 cars over ± 3 s) |
| Resolved to one partner within 3 m, no vision read | 7 of 10 |
| Logged digit misreads snapped right | 4 of 4 (559 and 999 to 959, 355 to 555, 81 to 01) |

Pass bar from the doc: 12 of 12, median 3 or fewer, every misread right.
Sets and misreads pass. The 12 of 12 is 10 of 10 here, because two key cases have no named partner:

- Report 10: the key names only #555, no second car, and the set is empty.
- Report 18: reporter #899 is not in the race's grid, which is the known unresolved case, so the set (#69) does not answer it.

## Findings

- The 8 m set is small and held the key partner every time. Report 16 is the widest, at 4 cars over ± 3 s.
- Three cases are not single-partner: reports 2, 46 and 23. Their closest gap is 3.5 to 5.6 m, past the 3 m bar, so they keep a one-car or two-car set rather than a decision.
- Reports 13 and 23 list #899 beside the key partner. The set holds every nearby car, so a ruling still has to choose between them; #899 is also the reporter in report 18, which is not in that grid. The league-to-sim number map (piece 3) is not tested here.
- Tie rule matters: with the camera car left in the set, a read of 559 ties between 555 and 959 and is refused. For reads of the other car the camera car must be left out of the set. 355 is the one read of the camera car's own number, so it snaps against the full set.
- Controls: a far read (777) and an empty set both return nothing.

## Limits of this test

- Four misreads is a small sample, and each was chosen after the fact from the logs. It shows the rule works on known slips, not how often a new slip lands inside the set.
- Camera car is taken from the key's reporter or victim, not read from the video (that is piece 4).
- The contact second is the key's own, so this test does not cover finding it (piece 2).
