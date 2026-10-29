# Racing telemetry judge: two league rules over the companion feed (29 Oct 2026)

Brock's question: can faultline rule racing from the data PitBot's companion already collects, rather than from video?
Scripts only: no model, no SAM, no proxy call, $0.
The league is the PitBot league of [the 28 Oct catalogue](../2026-10-28-league-catalogue/LOG.md); car numbers only.
This record tests each rule alone; [the racing pipeline](../2026-10-29-racing-pipeline/LOG.md) tests the pieces together.

## Pre-registration (written and committed before any score is computed)

### Inputs

- The 28 Oct catalogue, its feed events and its decision joins, used as they stand.
- The companion replay feeds, read for each car's shown incident count and track order.
- The league's sporting code, sections 2.1 and 9.2, from its rules pack.
- The league's 32 steward decisions, as the catalogue joined them.

### Rule A: incident limit (code 9.2)

- Limit per session: 20 on a two-race day (`HEAT 1` and `FEATURE`, format 2.1.1) and 25 on a one-race day (`RACE`, format 2.1.2).
- A car breaches when its last shown incident count in the session is over the limit.
- Sessions without a shown counter for every car are skipped, and this log names them.
- Truth: the incident-total decisions joined to a session with a feed (19, 20, 22, 25, 26, 27, 28; 21 has no race).
  A decision is found when a breaching car ends on the decision's stated total.
- Breaching cars with no decision are reported too.
  Code 9.9 says only reported incidents are penalised, so these are "not ruled", not false breaches.
- Pass mark: 6 of 7 found.

### Rule B: car-to-car contact referral (code 9.5)

- Every catalogue paired +4 event (two cars' +4 incident rises within 8 m, the sim's own contact count) is a referral to the stewards, naming both cars, the leader lap, the feed second and the stream seconds.
- The judge names the car behind as the likely offender: the car later in track order at the last frame before the event.
- Truth: the on-track decisions joined to a feed with a counter (11, 13, 14, 15, 16, 18, 23, 24, 46).
  Decision 1 is on Oulton, whose feed has no counter, and counts as not coverable.
- Measures:
  1. Coverage: decisions where a referral holds every named car with the leader lap within ±1.
  2. Offender: of the decisions that name a penalised car (23, 24, 46), how many the car-behind rule names.
  3. Load: referrals per session, against decisions per session.
- Pass mark: coverage 5 of 9 or more, and offender 2 of 3 or more.
  With 9 and 3 cases this is a feasibility read, not an accuracy claim.

### What would change the plan

- Rule A at 6 of 7 or more: an incident-limit ruling goes in the demo as a data-only ruling.
- Rule B at its mark: contact referral goes in, framed as "refers to the stewards", never as a penalty.
- Rule B under its mark: racing in the demo shows rule A plus the feed timeline only.

## Results

Two runs of the judge script write the same result file, byte for byte.

### Rule A: incident limit, 7 of 7 (pass)

Every incident-total decision with a feed has a breaching car on exactly the stated total.

| Decision | Session | Stated total | Limit | Breaching car on that total |
|---|---|---|---|---|
| 19 | Snetterton HEAT 1 | 21 | 20 | 18 (the penalised car) |
| 20 | Snetterton HEAT 1 | 31 | 20 | 5 |
| 22 | Snetterton FEATURE | 24 | 20 | 418 |
| 25 | Brands Hatch HEAT 1 | 30 | 20 | 26 |
| 26 | Brands Hatch HEAT 1 and FEATURE | 25 and 22 | 20 | 5, then 5 and 418 |
| 27 | Brands Hatch FEATURE | 21 | 20 | 84 |
| 28 | Brands Hatch FEATURE | 22 | 20 | 5 and 418 |

- Oulton HEAT 1 is skipped: its feed shows a counter for none of its 22 cars.
- 21 cars over the limit have no ruling on record: 2 at Spa, 1 in Snetterton HEAT 1, 6 at Donington, and all 12 in Season 2 (Cadwell and Thruxton).
  No incident-total decision exists for Season 2 at all, so the stewards either stopped ruling on totals or have not yet.
  Under code 9.9 these are "not ruled", and only Brock can say which.
- The truth set is 7 decisions from 2 race days, and the limit per format is read from codes 2.1 and 9.2, not from a steward.

### Rule B: contact referral, under the mark (fail)

- Coverage, every named car: 2 of 9 (mark 5).
  Coverage with two named cars: 3 of 9, not pre-registered and reported as a read.
- Offender, the car behind names the penalised car: 0 of 3 (mark 2).
  Decisions 23 and 24 have no referral at all; on 46 the feed pairs #01 with #334, as the catalogue found, and the ruling penalises #899.
- Covered: 11 (penalty, car behind #418), 15 (two referrals) and 46 (two of its three cars).
- Load: 100 referrals over 10 sessions against 10 on-track decisions.
  Most referrals are contacts nobody protested, and code 9.9 rules only reported incidents.
- The +4 pair rule misses the multi-car and lap-1 incidents (16, 18, 23, 24); why is not checked here.

## What it changes

- Per the pre-registered plan, racing in the demo shows rule A plus the feed timeline only.
- The incident-limit ruling is exact, data-only and replayable, and the steward decisions agree with it every time.
- Contact referral is not demo-ready on this feed; at most it lists "+4 contacts between two cars" on a timeline, never as a ruling.
