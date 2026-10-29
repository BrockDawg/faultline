"""Find the window of one protest in its session's feed: protest to (te, lap, stream seconds).

Input: a `faultline.adapters.pitbot.protest.Normalised` (the protest with names and numbers
resolved to sim numbers; it holds no outcome field), the `Feed` of the protest's own session,
and `events`, the combined list of `events.rises`, `events.paired_plus4` and
`events.collapses` for that feed. The race is given (`normalised.session`): the locator never
searches another session, and a feed for another session is refused with `LocatorError`.
The locator reads only what a protest holds: the cars it names, the reporter's car, the laps
it states and whether it says "last lap". It never reads a decision.

Protest cars are `normalised.cars` plus `normalised.reporter_car` when set. With none, the
answer is a `Refusal` with `missing_fact` "the protest names no car".

Scope. With stated laps (`normalised.laps`, plus the session's final leader lap when
`last_lap` is set), an event is in scope when its lap span meets a stated lap's span. The
event's lap span is [lowest, highest] over its leader lap and the own lap of every protest car
it holds, each read at `te_lo` and at `te_hi`; a stated lap's span is [stated - `LAP_SLACK`,
stated + `LAP_SLACK`] (`LAP_SLACK` is 1). This is the plan's "inside the stated lap ±1" read as
an overlap of spans, set on 29 Oct before any score: a rise whose counter was hidden for a
while can span several laps (leader lap 5 to 9), and it is in scope for "lap 7".
With no stated lap the whole session is in scope and the window carries `car_only: true`.
When `last_lap` is the only stated lap and the feed shows no leader lap at all, the answer is
a `Refusal` with `missing_fact` "no leader lap in the feed" (the final lap cannot be read);
when other laps are stated as well, those laps are searched.

Scoring, the pre-registered order (fixed before any score on the real reports; never tuned):
an event is a candidate only when it holds at least one protest car, and candidates rank by
1. a paired +4 (two counters up 4 or more within 8 metres),
2. a gap collapse with both a stall and an incident rise,
3. a gap collapse with either a stall or an incident rise,
4. an incident rise of 2 or more on a protest car.
A collapse with neither, and a rise of 1, are not candidates. Ties break by the most protest
cars held, then the earliest `te_lo`, then the earliest `te_hi`, then the cars by `numkey`.
No candidate in scope: a `Refusal` with `missing_fact` "no feed event holds a protest car on
the stated lap", or "... in the session" when no lap was stated.

The `Window` is the winning event's bounds padded `PAD_BEFORE_S` (3) seconds before and
`PAD_AFTER_S` (2) after. `contact_te`: for a pair or a collapse, the frame second of the
smallest gap between its two cars within the event's own bounds (the earliest on a tie), else
the event's `te_hi`; for a rise, the event's `te_hi` (the second the counter showed the step).
`lap` is the leader lap at `contact_te`, falling back to the event's leader lap at `te_hi`,
then at `te_lo`. `stream_s` is the padded window plus the session's stream offset, rounded to
1 decimal, or None when no offset is given. `why` is one blame-neutral line naming the event
kind and its seconds; it passes `faultline.lint` (no paths, no slashes, no names).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from faultline.adapters.pitbot.events import Event
from faultline.adapters.pitbot.feed import Feed
from faultline.adapters.pitbot.protest import Normalised
from faultline.roster import numkey

__all__ = [
    "LAP_SLACK",
    "NO_CAR",
    "NO_EVENT_LAP",
    "NO_EVENT_SESSION",
    "NO_LEADER_LAP",
    "PAD_AFTER_S",
    "PAD_BEFORE_S",
    "LocatorError",
    "Refusal",
    "Window",
    "locate",
]

LAP_SLACK = 1
PAD_BEFORE_S = 3
PAD_AFTER_S = 2
RISE_MIN = 2

NO_CAR = "the protest names no car"
NO_EVENT_LAP = "no feed event holds a protest car on the stated lap"
NO_EVENT_SESSION = "no feed event holds a protest car in the session"
NO_LEADER_LAP = "no leader lap in the feed"


class LocatorError(ValueError):
    """The locator was given inputs that do not belong together; the message names why."""


@dataclass(frozen=True)
class Window:
    """Where a protest's incident sits in the feed (see the module docstring)."""

    session: str
    te_lo: int
    te_hi: int
    contact_te: int
    lap: int | None
    car_only: bool
    event_kind: str
    event_cars: tuple[str, ...]
    protest_cars_held: tuple[str, ...]
    why: str
    stream_s: tuple[float, float] | None
    offset_error_s: float | None

    def as_dict(self) -> dict[str, Any]:
        """The ruling line's `window` object, plus `contact_te` and `car_only`."""
        return {
            "session": self.session,
            "te": [self.te_lo, self.te_hi],
            "lap": self.lap,
            "stream_s": None if self.stream_s is None else list(self.stream_s),
            "offset_error_s": self.offset_error_s,
            "contact_te": self.contact_te,
            "car_only": self.car_only,
        }


@dataclass(frozen=True)
class Refusal:
    """No window: `missing_fact` names the fact the feed could not give."""

    missing_fact: str
    session: str

    def as_dict(self) -> dict[str, Any]:
        return {"missing_fact": self.missing_fact, "session": self.session}


def _same_session(report_session: str, feed_session: str) -> bool:
    return report_session == feed_session or report_session.endswith("/" + feed_session)


def _rank(event: Event) -> int | None:
    """Priority of a candidate event (0 is best), or None when the kind does not qualify."""
    if event.kind == "paired_plus4":
        return 0
    if event.kind == "collapse":
        if event.stall and event.rise:
            return 1
        if event.stall or event.rise:
            return 2
        return None
    if event.kind == "rise":
        if event.inc_delta and event.inc_delta[0][1] >= RISE_MIN:
            return 3
        return None
    return None


def _in_scope(event: Event, laps: set[int], cars: set[str]) -> bool:
    seen: list[int] = [lap for lap in event.leader_lap if lap is not None]
    for num, lo, hi in event.car_laps:
        if num in cars:
            seen.extend(lap for lap in (lo, hi) if lap is not None)
    if not seen:
        return False
    lo, hi = min(seen), max(seen)
    return any(lo <= stated + LAP_SLACK and hi >= stated - LAP_SLACK for stated in laps)


def _final_leader_lap(feed: Feed) -> int | None:
    laps = [lap for sec in feed.seconds if (lap := feed.leader_lap(sec)) is not None]
    return max(laps) if laps else None


def _contact_te(feed: Feed, event: Event) -> int:
    if event.kind == "rise" or len(event.cars) != 2:
        return event.te_hi
    a, b = event.cars
    best: tuple[float, int] | None = None
    for sec in feed.seconds:
        if sec < event.te_lo or sec > event.te_hi:
            continue
        gap = feed.gap_m(a, b, sec)
        if gap is not None and (best is None or abs(gap) < best[0]):
            best = (abs(gap), sec)
    return event.te_hi if best is None else best[1]


def _cars_text(cars: Iterable[str]) -> str:
    cars = list(cars)
    if len(cars) == 1:
        return f"car {cars[0]}"
    return "cars " + ", ".join(cars[:-1]) + " and " + cars[-1]


def _why(event: Event) -> str:
    seconds = f"seconds {event.te_lo} to {event.te_hi}"
    if event.kind == "paired_plus4":
        return (
            f"Feed event: both incident counters up 4 or more within 8 metres, "
            f"{_cars_text(event.cars)}, {seconds}."
        )
    if event.kind == "collapse":
        marks = [w for w, on in (("a stall", event.stall), ("an incident rise", event.rise)) if on]
        return (
            f"Feed event: gap closed from {event.from_m} to {event.closest_m} metres "
            f"with {' and '.join(marks)}, {_cars_text(event.cars)}, {seconds}."
        )
    step = event.inc_delta[0][1] if event.inc_delta else 0
    return f"Feed event: incident counter up {step} on {_cars_text(event.cars)}, {seconds}."


def locate(
    normalised: Normalised,
    feed: Feed,
    events: Iterable[Event],
    offset_s: float | None = None,
    offset_error_s: float | None = None,
) -> Window | Refusal:
    """Find the protest's window in its own session's feed (see the module docstring)."""
    session = normalised.session
    if not _same_session(session, feed.session):
        raise LocatorError(f"report {normalised.id}: the feed is not the report's session.")
    cars = set(normalised.cars)
    if normalised.reporter_car:
        cars.add(normalised.reporter_car)
    if not cars:
        return Refusal(missing_fact=NO_CAR, session=session)

    laps = set(normalised.laps)
    if normalised.last_lap:
        final = _final_leader_lap(feed)
        if final is not None:
            laps.add(final)
        elif not laps:
            return Refusal(missing_fact=NO_LEADER_LAP, session=session)
    car_only = not laps and not normalised.last_lap

    best: tuple[tuple[Any, ...], Event] | None = None
    for event in events:
        held = cars.intersection(event.cars)
        if not held:
            continue
        rank = _rank(event)
        if rank is None:
            continue
        if not car_only and not _in_scope(event, laps, cars):
            continue
        key = (rank, -len(held), event.te_lo, event.te_hi, tuple(numkey(c) for c in event.cars))
        if best is None or key < best[0]:
            best = (key, event)
    if best is None:
        return Refusal(missing_fact=NO_EVENT_SESSION if car_only else NO_EVENT_LAP, session=session)

    event = best[1]
    te_lo, te_hi = event.te_lo - PAD_BEFORE_S, event.te_hi + PAD_AFTER_S
    contact = _contact_te(feed, event)
    lap = feed.leader_lap(contact)
    if lap is None:
        lap = event.leader_lap[1] if event.leader_lap[1] is not None else event.leader_lap[0]
    stream = None if offset_s is None else (round(te_lo + offset_s, 1), round(te_hi + offset_s, 1))
    return Window(
        session=session,
        te_lo=te_lo,
        te_hi=te_hi,
        contact_te=contact,
        lap=lap,
        car_only=car_only,
        event_kind=event.kind,
        event_cars=event.cars,
        protest_cars_held=tuple(sorted(cars.intersection(event.cars), key=numkey)),
        why=_why(event),
        stream_s=stream,
        offset_error_s=offset_error_s,
    )
