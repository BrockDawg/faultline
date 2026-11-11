"""Blame-neutral fact sheet for one window of a PitBot feed: what the telemetry shows, never why.

`facts(feed, events, cars, te_lo, te_hi, contact_te) -> list[str]`.

Inputs: a `Feed`; `events`, the session's feed events from `faultline.adapters.pitbot.events`
(pass `rises(feed) + paired_plus4(feed) + collapses(feed)`: the rise and paired +4 sentences
read the events given and nothing else, so a list without rises or pairs reads as none); `cars`,
the closed candidate set (sim numbers); the window `te_lo` to `te_hi`; and `contact_te`, the
window's reference second. Only cars in `cars` appear in any sentence, always as "car N".

Output: sentences in this fixed order, the same list for the same inputs:

1. each registered contact pair (two incident counter rises of 4 or more on different cars,
   overlapping, within 8 m: `events.paired_plus4`) between two cars of the set that meets the
   window, or one sentence saying the feed registered none;
2. always the fixed sentence `NO_CONTACT_SENTENCE`;
3. per car, each other incident counter step meeting the window, with its iRacing meaning for a
   step of 1 (off track) or 2 (loss of control); then the cars with no step shown in the window;
   then the cars whose counter the feed never shows;
4. per car, pit road seconds meeting the window, then each run of frame seconds under
   `events.STALL_MPS` (the collapse stall threshold) that starts in the window and is off pit
   road, followed to its end, with the lowest speed;
5. the race order of the set's cars at `contact_te - 3` and at `contact_te - 1`;
6. the gap and closing speed of the two closest cars of the set at `contact_te - 1`, from the
   frame before it (at most `feed.MAX_STEP_S` seconds earlier);
7. per car, its overall position at `contact_te - 1` and when its own lap ends.

Every measured sentence carries its resolution: "to the nearest second" on a 1 s feed, or "to
the nearest N seconds" when `feed.cadence_s` is N (2 on Oulton and Snetterton). Metres, speeds
in metres a second and seconds are written with 1 decimal where they are not whole frame
seconds. Units are words, never slashes, so every sentence passes `faultline.lint`.

Wording is blame-neutral by construction: no sentence uses a fault word or ties a contact to an
outcome, and none says that an absent registration means an absent contact.

Refusals raise `FactsError` naming the reason: an empty car set, a car not in the feed, or a
window that ends before it starts.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Sequence

from faultline.adapters.pitbot.events import PAIR_DELTA, STALL_MPS, Event
from faultline.adapters.pitbot.feed import MAX_STEP_S, Feed
from faultline.roster import numkey

__all__ = ["NO_CONTACT_SENTENCE", "STALL_FOLLOW_S", "FactsError", "facts"]

NO_CONTACT_SENTENCE = "No registered contact does not mean no contact."
# How far past the window a slow run that starts inside it is followed to its end.
STALL_FOLLOW_S = 60

_STEP_MEANING = {1: "off track", 2: "loss of control"}


class FactsError(ValueError):
    """A fact sheet could not be built; the message names the reason."""


def _f1(value: float) -> str:
    text = f"{round(value, 1):.1f}"
    return "0.0" if text == "-0.0" else text


def _car(num: str) -> str:
    return f"car {num}"


def _cars(nums: Iterable[str]) -> str:
    items = [_car(n) for n in nums]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _span(lo: int, hi: int) -> str:
    return f"at second {lo}" if lo == hi else f"between second {lo} and second {hi}"


def _seconds_word(n: int) -> str:
    return "1 second" if n == 1 else f"{n} seconds"


def _resolution(feed: Feed) -> str:
    return (
        "to the nearest second"
        if feed.cadence_s <= 1
        else f"to the nearest {feed.cadence_s} seconds"
    )


def _meets(event: Event, te_lo: int, te_hi: int) -> bool:
    return event.te_hi >= te_lo and event.te_lo <= te_hi


def _between(feed: Feed, lo: int, hi: int) -> list[int]:
    return feed.seconds[
        bisect.bisect_left(feed.seconds, lo) : bisect.bisect_right(feed.seconds, hi)
    ]


def _event_key(e: Event) -> tuple:
    return (e.te_lo, e.te_hi, tuple(numkey(c) for c in e.cars))


def _pair_facts(feed: Feed, pairs: list[Event], res: str, te_lo: int, te_hi: int) -> list[str]:
    if not pairs:
        return [
            f"The feed registered no contact pair among these cars {_span(te_lo, te_hi)}, {res}."
        ]
    out = []
    for e in pairs:
        a, b = e.cars
        out.append(
            f"The feed registered a contact pair between {_car(a)} and {_car(b)} "
            f"{_span(e.te_lo, e.te_hi)}, {res}: both incident counters rose by "
            f"{PAIR_DELTA} or more, and the two cars were {_f1(e.closest_m or 0.0)} metres "
            "apart at the closest."
        )
    return out


def _counter_facts(
    feed: Feed,
    rises: list[Event],
    pairs: list[Event],
    cars: list[str],
    res: str,
    te_lo: int,
    te_hi: int,
) -> list[str]:
    out: list[str] = []
    stepped: set[str] = set()
    for num in cars:
        for r in rises:
            if r.cars[0] != num:
                continue
            step = r.inc_delta[0][1]
            stepped.add(num)
            if step >= PAIR_DELTA and any(
                num in p.cars and p.te_lo <= r.te_hi and p.te_hi >= r.te_lo for p in pairs
            ):
                continue  # stated in its contact pair sentence
            meaning = _STEP_MEANING.get(step)
            what = f"rose by {step}" + (f", the step for {meaning}," if meaning else "")
            out.append(
                f"The incident counter of {_car(num)} {what} {_span(r.te_lo, r.te_hi)}, {res}."
            )
    quiet = [n for n in cars if n not in stepped and feed.counter_shown(n)]
    if quiet:
        noun, verb = ("counter", "shows") if len(quiet) == 1 else ("counters", "show")
        out.append(
            f"The incident {noun} of {_cars(quiet)} {verb} no step {_span(te_lo, te_hi)}, {res}."
        )
    hidden = [n for n in cars if not feed.counter_shown(n)]
    if hidden:
        noun = "counter" if len(hidden) == 1 else "counters"
        out.append(
            f"The feed never shows the incident {noun} of {_cars(hidden)}, "
            "so no step can be read there."
        )
    return out


def _runs(
    seconds: Sequence[int], flags: Sequence[bool], all_seconds: Sequence[int]
) -> list[list[int]]:
    """Runs of flagged seconds that are consecutive frame seconds of the feed."""
    index = {s: i for i, s in enumerate(all_seconds)}
    runs: list[list[int]] = []
    for sec, flag in zip(seconds, flags, strict=True):
        if not flag:
            continue
        if runs and index[sec] == index[runs[-1][-1]] + 1:
            runs[-1].append(sec)
        else:
            runs.append([sec])
    return runs


def _motion_facts(feed: Feed, cars: list[str], res: str, te_lo: int, te_hi: int) -> list[str]:
    out: list[str] = []
    span = _between(feed, te_lo, te_hi + STALL_FOLLOW_S)
    for num in cars:
        in_pit = [bool(feed.pit(num, s)) for s in span]
        for run in _runs(span, in_pit, feed.seconds):
            if run[0] <= te_hi and run[-1] >= te_lo:
                out.append(
                    f"{_car(num).capitalize()} was on pit road {_span(run[0], run[-1])}, {res}."
                )
        speeds = {s: feed.speed_mps(num, s) for s in span}
        slow = [
            not pit and (v := speeds[s]) is not None and v < STALL_MPS
            for s, pit in zip(span, in_pit, strict=True)
        ]
        for run in _runs(span, slow, feed.seconds):
            if not te_lo <= run[0] <= te_hi:
                continue
            low = min(v for s in run if (v := speeds[s]) is not None)
            out.append(
                f"{_car(num).capitalize()} moved under {_f1(STALL_MPS)} metres a second "
                f"{_span(run[0], run[-1])}, lowest {_f1(low)} metres a second, {res}."
            )
    return out


def _order_fact(feed: Feed, cars: list[str], te: int, back: int, contact_te: int, res: str) -> str:
    when = f"At second {te}, {_seconds_word(back)} before second {contact_te}"
    order = [n for n in feed.order_at(te) if n in set(cars)]
    if not order:
        return f"{when}, the feed has no frame placing these cars, {res}."
    text = f"{when}, the race order of these cars was {', '.join(_car(n) for n in order)}"
    missing = [n for n in cars if n not in order]
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        text += f", and {_cars(missing)} {verb} not in that frame"
    return f"{text}, {res}."


def _closing_fact(feed: Feed, cars: list[str], contact_te: int, res: str) -> str:
    t1 = feed.second_at(contact_te - 1)
    lead = f"At second {contact_te - 1}"
    if t1 is None:
        return f"{lead}, the feed has no frame, so no gap or closing speed can be read, {res}."
    best: tuple[float, tuple, str, str, float] | None = None
    for i, a in enumerate(cars):
        for b in cars[i + 1 :]:
            g = feed.gap_m(a, b, t1)
            if g is None:
                continue
            ahead, behind = (a, b) if g >= 0 else (b, a)
            key = (abs(g), (numkey(ahead), numkey(behind)), ahead, behind, abs(g))
            if best is None or key[:2] < best[:2]:
                best = key
    if best is None:
        return (
            f"{lead}, fewer than two of these cars are in the frame, so no gap can be read, {res}."
        )
    _abs, _k, ahead, behind, gap = best
    text = (
        f"{lead}, the two closest of these cars were {_car(behind)}, "
        f"{_f1(gap)} metres behind {_car(ahead)}"
    )
    i = bisect.bisect_left(feed.seconds, t1)
    t0 = feed.seconds[i - 1] if i > 0 else None
    prev = None if t0 is None or t1 - t0 > MAX_STEP_S else feed.gap_m(ahead, behind, t0)
    if prev is None or t0 is None:
        return f"{text}; the frame before holds no gap to compare, {res}."
    rate = (prev - gap) / (t1 - t0)
    if round(rate, 1) > 0:
        trend = f"the gap closed at {_f1(rate)} metres a second"
    elif round(rate, 1) < 0:
        trend = f"the gap grew at {_f1(-rate)} metres a second"
    else:
        trend = "the gap changed by under 0.1 metres a second"
    return f"{text}, and since second {t0} {trend}, {res}."


def _position(feed: Feed, num: str, te: int) -> int | None:
    order = feed.order_at(te)
    return order.index(num) + 1 if num in order else None


def _position_facts(feed: Feed, cars: list[str], contact_te: int, res: str) -> list[str]:
    out: list[str] = []
    t1 = contact_te - 1
    for num in cars:
        p0 = _position(feed, num, t1)
        lap0 = feed.lap_at(num, t1)
        if p0 is None or lap0 is None:
            out.append(
                f"At second {t1}, the feed places no position or lap for {_car(num)}, {res}."
            )
            continue
        end = next(
            (
                s
                for s in feed.seconds
                if s > t1 and (lap := feed.lap_at(num, s)) is not None and lap > lap0
            ),
            None,
        )
        if end is None:
            out.append(
                f"{_car(num).capitalize()} ran in position {p0} at second {t1}, "
                f"and its lap {lap0} does not end in the feed, {res}."
            )
            continue
        p1 = _position(feed, num, end)
        if p1 is None:
            continue
        moved = p1 - p0
        if moved > 0:
            change = f"{moved} position{'s' if moved > 1 else ''} lost"
        elif moved < 0:
            change = f"{-moved} position{'s' if moved < -1 else ''} gained"
        else:
            change = "the same position"
        out.append(
            f"{_car(num).capitalize()} ran in position {p0} at second {t1} and in position "
            f"{p1} when its lap {lap0} ended at second {end}: {change}, {res}."
        )
    return out


def facts(
    feed: Feed,
    events: Iterable[Event],
    cars: Iterable[str],
    te_lo: int,
    te_hi: int,
    contact_te: int,
) -> list[str]:
    """The window's fact sheet, in the fixed order of the module docstring."""
    closed = sorted(set(cars), key=numkey)
    if not closed:
        raise FactsError("no car was given: the closed set is empty.")
    unknown = [n for n in closed if n not in feed.nums]
    if unknown:
        raise FactsError(f"{len(unknown)} car(s) of the set are not in the feed.")
    if te_hi < te_lo:
        raise FactsError(f"window ends before it starts ({te_lo} to {te_hi}).")
    members = set(closed)
    events = sorted(
        (e for e in events if _meets(e, te_lo, te_hi) and set(e.cars) <= members), key=_event_key
    )
    pairs = [e for e in events if e.kind == "paired_plus4"]
    rises = [e for e in events if e.kind == "rise"]
    res = _resolution(feed)

    out = _pair_facts(feed, pairs, res, te_lo, te_hi)
    out.append(NO_CONTACT_SENTENCE)
    out += _counter_facts(feed, rises, pairs, closed, res, te_lo, te_hi)
    out += _motion_facts(feed, closed, res, te_lo, te_hi)
    out.append(_order_fact(feed, closed, contact_te - 3, 3, contact_te, res))
    out.append(_order_fact(feed, closed, contact_te - 1, 1, contact_te, res))
    out.append(_closing_fact(feed, closed, contact_te, res))
    out += _position_facts(feed, closed, contact_te, res)
    return out
