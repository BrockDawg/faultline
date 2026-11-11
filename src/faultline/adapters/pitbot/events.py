"""Feed events for one session: incident rises, paired +4 rises, and gap collapses.

Input is a `faultline.adapters.pitbot.feed.Feed`. Every function reads the feed at its own
frame seconds only (`Feed.seconds`), never between them, so no held reading enters an event.
Output is a list of `Event` (frozen), sorted by (`te_lo`, `kind`, `cars` by `numkey`), then
`te_hi`. Nothing here reads a name.

`rises(feed)`, kind "rise": for each car, walk the seconds where its incident counter is shown
(not -1); each step up from the previous shown value is one rise, `te_lo` the second of the
previous shown value and `te_hi` the second of the new one. An intermittently shown counter
therefore gives wide bounds, and a car whose counter is never shown gives no rise.

`paired_plus4(feed)`, kind "paired_plus4": two rises of `PAIR_DELTA` or more on different cars
whose bounds overlap, where the cars were within `PAIR_NEAR_M` metres at some frame second
inside the overlap. The event's bounds are the overlap; `closest_m` is the smallest such gap.

`collapses(feed)`, kind "collapse": at a frame second, two cars both off pit road are at most
`COLLAPSE_TO_M` apart, and at some frame second in the `COLLAPSE_WITHIN_S` seconds before
(`te - 3 <= t < te`) they were `COLLAPSE_FROM_M` or more apart. Seconds of one pair at most
`COLLAPSE_MERGE_S` apart merge into one event. `from_m` is the widest earlier gap at the first
second, `closest_m` the smallest gap over the merged seconds. `stall_cars` are the event's cars
whose speed fell under `STALL_MPS` at a frame second within `STALL_AFTER_S` of `te_lo`;
`rise_cars` are the event's cars with a rise whose bounds meet `te_lo + RISE_WINDOW`.

Every event carries the leader lap and each car's own lap (`Feed.lap_at`) at `te_lo` and at
`te_hi`, the car's counter step for rises and pairs, and metres rounded to 1 decimal.

`all_events(feed)` is the three lists in one, from one `rises` pass, sorted the same way: the
list the CLI, the locator and the facts read.

The semantics are those of the 28 Oct league catalogue (a private script, read in place by the
drift test, never copied here), rewritten on faultline's
`Feed`. The departures, each checked on the 11 corpus sessions by the private drift test:
- The collapse look-back is the frame seconds in the three seconds before, by time, as the
  pre-registered "within 3 s" says. The catalogue took the three previous frame lines, which on
  a feed with a repeated second just before reach back less than three seconds. This is the one
  departure that changes a count: 504 collapses here against the catalogue's 501, the three
  extras being Cadwell FEATURE cars 12/82 at 92 and 18/123 at 391, and Thruxton HEAT 1 cars
  57/66 at 1231, each with a wide gap at the third second back that the catalogue's three lines
  did not reach. Paired +4 (100) and every catalogue collapse, with its flags, are unchanged.
- `closest_m` on a merged collapse is the smallest gap over all its seconds; the catalogue kept
  the gap at the first second (`to_m`). No count changes.
- Rises cover every car with a shown counter, also a car only ever seen in `rows[]` (the
  catalogue walked only cars in `positions[]`). Such a car has no position, so it never joins a
  pair or a collapse. No count changes.
- Within one int second the later file line wins, car by car (the `Feed` rule); the catalogue
  sorted frames by float `timeElapsed`, so the larger float won. No count changes.
- A negative or non-finite `pct` is dropped at load by the `Feed`; the catalogue kept it. The
  corpus holds none.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from faultline.adapters.pitbot.feed import Feed
from faultline.roster import numkey

__all__ = [
    "COLLAPSE_FROM_M",
    "COLLAPSE_MERGE_S",
    "COLLAPSE_TO_M",
    "COLLAPSE_WITHIN_S",
    "PAIR_DELTA",
    "PAIR_NEAR_M",
    "RISE_WINDOW",
    "STALL_AFTER_S",
    "STALL_MPS",
    "Event",
    "all_events",
    "collapses",
    "paired_plus4",
    "rises",
]

# Thresholds pre-registered for the 28 Oct league catalogue (the private script, lines 25-28,
# and its LOG).
# Copied unchanged; never tune them to a result.
COLLAPSE_FROM_M = 8.0
COLLAPSE_TO_M = 2.0
COLLAPSE_WITHIN_S = 3
COLLAPSE_MERGE_S = 10
STALL_MPS = 12.0
STALL_AFTER_S = 5
RISE_WINDOW = (-2, 5)
PAIR_NEAR_M = 8.0
# The +4 of "paired +4" (catalogue `paired_plus4`: `delta >= 4`, the W0-02 pairing).
PAIR_DELTA = 4

_KIND_RISE = "rise"
_KIND_PAIR = "paired_plus4"
_KIND_COLLAPSE = "collapse"


@dataclass(frozen=True)
class Event:
    """One feed event. Fields that do not apply to a kind stay empty or None.

    `cars`: sim numbers, sorted by `numkey`. `leader_lap`: the leader lap at (`te_lo`, `te_hi`).
    `car_laps`: per car in `cars` order, (num, own lap at `te_lo`, own lap at `te_hi`).
    `inc_delta`: per car, (num, counter step); rises and pairs only. `closest_m`: smallest gap
    in metres, 1 decimal; pairs and collapses. `from_m`, `stall_cars`, `rise_cars`, `stall`,
    `rise`: collapses only.
    """

    kind: str
    te_lo: int
    te_hi: int
    cars: tuple[str, ...]
    leader_lap: tuple[int | None, int | None]
    car_laps: tuple[tuple[str, int | None, int | None], ...]
    inc_delta: tuple[tuple[str, int], ...] = ()
    closest_m: float | None = None
    from_m: float | None = None
    stall_cars: tuple[str, ...] = ()
    rise_cars: tuple[str, ...] = ()
    stall: bool = False
    rise: bool = False


def _sorted_cars(cars: set[str] | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(cars), key=numkey))


def _event(feed: Feed, kind: str, te_lo: int, te_hi: int, cars: tuple[str, ...], **rest) -> Event:
    return Event(
        kind=kind,
        te_lo=te_lo,
        te_hi=te_hi,
        cars=cars,
        leader_lap=(feed.leader_lap(te_lo), feed.leader_lap(te_hi)),
        car_laps=tuple((c, feed.lap_at(c, te_lo), feed.lap_at(c, te_hi)) for c in cars),
        **rest,
    )


def _sort(events: list[Event]) -> list[Event]:
    return sorted(
        events,
        key=lambda e: (e.te_lo, e.kind, tuple(numkey(c) for c in e.cars), e.te_hi, e.closest_m),
    )


def _between(feed: Feed, lo: int, hi: int) -> list[int]:
    """Frame seconds in the closed range [lo, hi]."""
    return feed.seconds[
        bisect.bisect_left(feed.seconds, lo) : bisect.bisect_right(feed.seconds, hi)
    ]


def rises(feed: Feed) -> list[Event]:
    """Every step up of a shown incident counter (see the module docstring)."""
    out: list[Event] = []
    for num in feed.nums:
        prev: tuple[int, int] | None = None
        for sec in feed.seconds:
            value = feed.inc(num, sec)
            if value is None:
                continue
            if prev is not None and value > prev[1]:
                cars = (num,)
                out.append(
                    _event(
                        feed, _KIND_RISE, prev[0], sec, cars, inc_delta=((num, value - prev[1]),)
                    )
                )
            prev = (sec, value)
    return _sort(out)


def _abs_gap(feed: Feed, a: str, b: str, sec: int) -> float | None:
    gap = feed.gap_m(a, b, sec)
    return None if gap is None else abs(gap)


def paired_plus4(feed: Feed, all_rises: list[Event] | None = None) -> list[Event]:
    """Two +4 rises on different cars, overlapping, within 8 m inside the overlap."""
    if all_rises is None:
        all_rises = rises(feed)
    big = [r for r in all_rises if r.kind == _KIND_RISE and r.inc_delta[0][1] >= PAIR_DELTA]
    out: list[Event] = []
    for i, a in enumerate(big):
        for b in big[i + 1 :]:
            car_a, car_b = a.cars[0], b.cars[0]
            if car_a == car_b:
                continue
            lo, hi = max(a.te_lo, b.te_lo), min(a.te_hi, b.te_hi)
            if lo > hi:
                continue
            near = [
                g
                for sec in _between(feed, lo, hi)
                if (g := _abs_gap(feed, car_a, car_b, sec)) is not None and g <= PAIR_NEAR_M
            ]
            if not near:
                continue
            cars = _sorted_cars((car_a, car_b))
            deltas = dict(a.inc_delta + b.inc_delta)
            out.append(
                _event(
                    feed,
                    _KIND_PAIR,
                    lo,
                    hi,
                    cars,
                    inc_delta=tuple((c, deltas[c]) for c in cars),
                    closest_m=round(min(near), 1),
                )
            )
    return _sort(out)


def _raw_collapses(feed: Feed) -> list[tuple[tuple[str, ...], int, float, float]]:
    """(pair, second, widest earlier gap, gap now) for every collapse second, unrounded."""
    raw: list[tuple[tuple[str, ...], int, float, float]] = []
    track_m = feed.track_m
    for idx, sec in enumerate(feed.seconds):
        here: list[tuple[float, str]] = []
        for num in feed.nums:
            pct = feed.pct(num, sec)
            if pct is not None and not feed.pit(num, sec):
                here.append((pct, num))
        here.sort()
        looks_back = [
            t
            for t in feed.seconds[max(0, idx - COLLAPSE_WITHIN_S) : idx]
            if sec - t <= COLLAPSE_WITHIN_S
        ]
        for k, (pa, a) in enumerate(here):
            # Cars ahead by fraction, then wrapped round the line (the first three only).
            ahead = here[k + 1 :] + [(p + 1.0, m) for p, m in here[:3]]
            for pb, b in ahead:
                if (pb - pa) * track_m > COLLAPSE_TO_M:
                    break
                now = _abs_gap(feed, a, b, sec)
                if a == b or now is None or now > COLLAPSE_TO_M:
                    continue
                before = [g for t in looks_back if (g := _abs_gap(feed, a, b, t)) is not None]
                if before and max(before) >= COLLAPSE_FROM_M:
                    raw.append((_sorted_cars((a, b)), sec, max(before), now))
    return raw


def collapses(feed: Feed, all_rises: list[Event] | None = None) -> list[Event]:
    """Gap collapses from 8 m or more to 2 m or less within 3 s, with stall and rise flags."""
    if all_rises is None:
        all_rises = rises(feed)
    merged: list[dict] = []
    raw = sorted(_raw_collapses(feed), key=lambda x: (tuple(numkey(c) for c in x[0]), x[1]))
    for pair, sec, frm, now in raw:
        last = merged[-1] if merged else None
        if last and last["cars"] == pair and sec - last["te_hi"] <= COLLAPSE_MERGE_S:
            last["te_hi"] = sec
            last["closest"] = min(last["closest"], now)
            continue
        merged.append({"cars": pair, "te_lo": sec, "te_hi": sec, "from": frm, "closest": now})
    out: list[Event] = []
    for m in merged:
        cars, t0 = m["cars"], m["te_lo"]
        stall = _sorted_cars(
            [
                c
                for c in cars
                for t in _between(feed, t0, t0 + STALL_AFTER_S)
                if (s := feed.speed_mps(c, t)) is not None and s < STALL_MPS
            ]
        )
        rise = _sorted_cars(
            [
                r.cars[0]
                for r in all_rises
                if r.kind == _KIND_RISE
                and r.cars[0] in cars
                and r.te_lo <= t0 + RISE_WINDOW[1]
                and r.te_hi >= t0 + RISE_WINDOW[0]
            ]
        )
        out.append(
            _event(
                feed,
                _KIND_COLLAPSE,
                t0,
                m["te_hi"],
                cars,
                closest_m=round(m["closest"], 1),
                from_m=round(m["from"], 1),
                stall_cars=stall,
                rise_cars=rise,
                stall=bool(stall),
                rise=bool(rise),
            )
        )
    return _sort(out)


def all_events(feed: Feed) -> list[Event]:
    """Rises, paired +4 and collapses in one list, sorted as each list is."""
    found = rises(feed)
    return _sort(found + paired_plus4(feed, found) + collapses(feed, found))
