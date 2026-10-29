"""Tests for the protest locator on the synthetic feed and on feeds built in the test."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from faultline import lint
from faultline.adapters.pitbot import events as ev
from faultline.adapters.pitbot.feed import Feed
from faultline.adapters.pitbot.locator import (
    NO_CAR,
    NO_EVENT_LAP,
    NO_EVENT_SESSION,
    NO_LEADER_LAP,
    LocatorError,
    Refusal,
    Window,
    locate,
)
from faultline.adapters.pitbot.protest import Normalised

RACING = Path(__file__).resolve().parents[2] / "data" / "racing"
BANNED = {
    "verdict",
    "penalty_points",
    "ruling_reason",
    "penalised",
    "penalised_car",
    "evidence_url",
}


def protest(
    cars: tuple[str, ...] = (),
    laps: tuple[int, ...] = (),
    reporter: str | None = None,
    last_lap: bool = False,
    session: str = "S1/RACE",
) -> Normalised:
    return Normalised(
        id="t1",
        session=session,
        text="synthetic protest",
        cars=cars,
        reporter_car=reporter,
        laps=laps,
        last_lap=last_lap,
        unresolved=(),
    )


def all_events(feed: Feed) -> list[ev.Event]:
    rises = ev.rises(feed)
    return rises + ev.paired_plus4(feed, rises) + ev.collapses(feed, rises)


@pytest.fixture
def small_events(small_feed: Feed) -> list[ev.Event]:
    return all_events(small_feed)


# ---------------------------------------------------------------- the contract


def test_normalised_holds_no_outcome_field() -> None:
    fields = {f.name for f in dataclasses.fields(Normalised)}
    assert not fields & BANNED


def test_locate_reads_no_decision_argument() -> None:
    import inspect

    params = set(inspect.signature(locate).parameters)
    assert params == {"normalised", "feed", "events", "offset_s", "offset_error_s"}


# ---------------------------------------------------------------- the synthetic feed


def test_cars_2_and_3_on_the_lap_find_the_pair(small_feed: Feed, small_events) -> None:
    w = locate(protest(("2", "3"), laps=(4,)), small_feed, small_events)
    assert isinstance(w, Window)
    assert w.event_kind == "paired_plus4"
    assert w.event_cars == ("2", "3")
    assert w.protest_cars_held == ("2", "3")
    assert (w.te_lo, w.te_hi) == (106 - 3, 107 + 2)
    assert 106 <= w.contact_te <= 107
    assert w.lap == 4
    assert w.car_only is False
    assert w.session == "S1/RACE"
    assert w.stream_s is None


def test_pair_beats_the_collapse_on_the_same_cars(small_feed: Feed, small_events) -> None:
    # The collapse at 106 has both a stall and a rise; a paired +4 still ranks first.
    assert any(e.kind == "collapse" and e.stall and e.rise for e in small_events)
    w = locate(protest(("3",), laps=(3,)), small_feed, small_events)
    assert isinstance(w, Window) and w.event_kind == "paired_plus4"


def test_collapse_wins_when_no_pair_is_given(small_feed: Feed, small_events) -> None:
    no_pairs = [e for e in small_events if e.kind != "paired_plus4"]
    w = locate(protest(("2", "3"), laps=(4,)), small_feed, no_pairs)
    assert isinstance(w, Window)
    assert w.event_kind == "collapse"
    assert w.contact_te == 106
    assert (w.te_lo, w.te_hi) == (103, 108)


def test_car_4_finds_its_plus_2_rise(small_feed: Feed, small_events) -> None:
    w = locate(protest(("4",), laps=(4,)), small_feed, small_events)
    assert isinstance(w, Window)
    assert w.event_kind == "rise"
    assert w.event_cars == ("4",)
    assert (w.te_lo, w.te_hi, w.contact_te) == (126, 132, 130)


def test_a_plus_1_rise_is_not_a_candidate(small_feed: Feed, small_events) -> None:
    only_plus1 = [e for e in small_events if not (e.kind == "rise" and e.te_hi == 130)]
    r = locate(protest(("4",), laps=(4,)), small_feed, only_plus1)
    assert r == Refusal(missing_fact=NO_EVENT_LAP, session="S1/RACE")


def test_car_5_refuses(small_feed: Feed, small_events) -> None:
    r = locate(protest(("5",), laps=(4,)), small_feed, small_events)
    assert r == Refusal(missing_fact=NO_EVENT_LAP, session="S1/RACE")


def test_car_5_with_no_lap_refuses_for_the_session(small_feed: Feed, small_events) -> None:
    r = locate(protest(("5",)), small_feed, small_events)
    assert r == Refusal(missing_fact=NO_EVENT_SESSION, session="S1/RACE")


def test_a_lap_far_from_any_event_refuses(small_feed: Feed, small_events) -> None:
    r = locate(protest(("2", "3"), laps=(10,)), small_feed, small_events)
    assert isinstance(r, Refusal) and r.missing_fact == NO_EVENT_LAP


def test_lap_slack_is_one(small_feed: Feed, small_events) -> None:
    # Leader lap 4 and the cars' own lap 3: lap 5 is within one, lap 6 is not.
    assert isinstance(locate(protest(("2",), laps=(5,)), small_feed, small_events), Window)
    assert isinstance(locate(protest(("2",), laps=(6,)), small_feed, small_events), Refusal)
    # Lap 2 is within one of car 2's own lap 3 (the leader is on 4).
    assert isinstance(locate(protest(("2",), laps=(2,)), small_feed, small_events), Window)


def test_no_car_refuses(small_feed: Feed, small_events) -> None:
    r = locate(protest((), laps=(4,)), small_feed, small_events)
    assert r == Refusal(missing_fact=NO_CAR, session="S1/RACE")


def test_reporter_car_counts_as_a_protest_car(small_feed: Feed, small_events) -> None:
    w = locate(protest((), laps=(4,), reporter="4"), small_feed, small_events)
    assert isinstance(w, Window) and w.event_cars == ("4",)


def test_no_stated_lap_searches_the_session_car_only(small_feed: Feed, small_events) -> None:
    w = locate(protest(("4",)), small_feed, small_events)
    assert isinstance(w, Window)
    assert w.car_only is True
    assert w.as_dict()["car_only"] is True


def test_last_lap_means_the_final_leader_lap(small_feed: Feed, small_events) -> None:
    w = locate(protest(("4",), last_lap=True), small_feed, small_events)
    assert isinstance(w, Window) and w.car_only is False and w.event_kind == "rise"


def test_stream_seconds_and_as_dict(small_feed: Feed, small_events) -> None:
    w = locate(
        protest(("2", "3"), laps=(4,)),
        small_feed,
        small_events,
        offset_s=1395.55,
        offset_error_s=2.0,
    )
    assert isinstance(w, Window)
    assert w.stream_s == (round(103 + 1395.55, 1), round(109 + 1395.55, 1))
    d = w.as_dict()
    assert set(d) == {
        "session",
        "te",
        "lap",
        "stream_s",
        "offset_error_s",
        "contact_te",
        "car_only",
    }
    assert d["te"] == [103, 109]
    assert d["stream_s"] == list(w.stream_s)
    assert d["offset_error_s"] == 2.0
    json.dumps(d)  # plain JSON


def test_why_is_blame_neutral_and_lint_clean(small_feed: Feed, small_events) -> None:
    cases = [
        (protest(("2", "3"), laps=(4,)), small_events),
        (protest(("2", "3"), laps=(4,)), [e for e in small_events if e.kind != "paired_plus4"]),
        (protest(("4",), laps=(4,)), small_events),
    ]
    for p, events in cases:
        w = locate(p, small_feed, events)
        assert isinstance(w, Window)
        lint.assert_clean(w.why, names=["Test Driver A", "Test Driver B"])
        assert "/" not in w.why
        assert str(w.te_lo + 3) in w.why
        for word in ("fault", "caused", "blame", "dive", "careless"):
            assert word not in w.why.casefold()


def test_another_session_feed_is_refused(small_feed: Feed, small_events) -> None:
    with pytest.raises(LocatorError):
        locate(protest(("2",), laps=(4,), session="S1/HEAT 1"), small_feed, small_events)


def test_same_inputs_give_the_same_window(small_feed: Feed, small_events) -> None:
    a = locate(protest(("2", "3"), laps=(4,)), small_feed, small_events)
    b = locate(protest(("2", "3"), laps=(4,)), small_feed, list(reversed(small_events)))
    assert a == b


# ---------------------------------------------------------------- tie-breaks on built feeds

# Cars move 0.01 of a lap a second on Thruxton, all on lap 1. Pairs sit 0.001 of a lap apart
# (3.8 m, inside 8 m) with constant gaps, so no collapse fires.
_BASE = {"A": 0.500, "B": 0.501, "C": 0.300, "D": 0.301, "E": 0.100, "F": 0.700}
# Car, the second its counter steps, and the step.
_STEPS = {"A": (20, 4), "B": (20, 4), "C": (40, 4), "D": (40, 4), "E": (10, 2)}
_NUMS = {"A": "11", "B": "12", "C": "21", "D": "22", "E": "31", "F": "41"}


def _frames() -> list[dict]:
    frames = []
    for te in range(0, 61):
        positions, rows = [], []
        for car, base in _BASE.items():
            num = _NUMS[car]
            positions.append({"num": num, "pct": round(base + 0.004 * te, 4), "pit": False})
            step = _STEPS.get(car)
            inc = step[1] if step and te >= step[0] else 0
            rows.append({"num": num, "inc": inc, "lap": 1})
        frames.append(
            {
                "timeElapsed": te,
                "session": "RACE",
                "track": "Thruxton Circuit",
                "leaderLap": 1,
                "positions": positions,
                "rows": rows,
            }
        )
    return frames


@pytest.fixture
def built(tmp_path: Path, feed_writer: Callable[[list[dict], Path], Path]):
    feed = Feed.load(feed_writer(_frames(), tmp_path / "replay-built.ndjson.gz"), "RACE")
    events = all_events(feed)
    assert [e.cars for e in events if e.kind == "paired_plus4"] == [("11", "12"), ("21", "22")]
    assert not [e for e in events if e.kind == "collapse"]
    return feed, events


def test_tie_on_cars_held_breaks_by_earliest(built) -> None:
    feed, events = built
    w = locate(protest(("11", "21"), laps=(1,)), feed, events)
    assert isinstance(w, Window) and w.event_cars == ("11", "12")


def test_more_protest_cars_held_beats_earlier(built) -> None:
    feed, events = built
    w = locate(protest(("11", "21", "22"), laps=(1,)), feed, events)
    assert isinstance(w, Window) and w.event_cars == ("21", "22")
    assert w.protest_cars_held == ("21", "22")


def test_a_pair_beats_an_earlier_plus_2_rise(built) -> None:
    feed, events = built
    w = locate(protest(("31", "21"), laps=(1,)), feed, events)
    assert isinstance(w, Window) and w.event_kind == "paired_plus4"
    alone = locate(protest(("31",), laps=(1,)), feed, events)
    assert isinstance(alone, Window) and alone.event_kind == "rise"
    assert alone.contact_te == 10


def test_a_car_with_no_event_refuses_on_a_built_feed(built) -> None:
    feed, events = built
    assert locate(protest(("41",), laps=(1,)), feed, events) == Refusal(
        missing_fact=NO_EVENT_LAP, session="S1/RACE"
    )


# ---------------------------------------------------------------- lap spans and leader laps


def _hidden_counter_frames(leader: bool = True) -> list[dict]:
    """One car parked mid-lap; the leader lap climbs 1 every 10 s from lap 1 at second 0.

    The car's counter shows 0 at second 0, is hidden (-1) until second 50, then shows 2: one
    +2 rise from second 0 to second 50, spanning leader laps 1 to 6.
    """
    frames = []
    for te in range(0, 61):
        lap = 1 + te // 10
        inc = 0 if te == 0 else (2 if te >= 50 else -1)
        frame = {
            "timeElapsed": te,
            "session": "RACE",
            "track": "Thruxton Circuit",
            "positions": [{"num": "7", "pct": 0.5, "pit": False}],
            "rows": [{"num": "7", "inc": inc, "lap": lap}],
        }
        if leader:
            frame["leaderLap"] = lap
        frames.append(frame)
    return frames


def test_a_rise_spanning_several_laps_is_in_scope_for_a_lap_inside(
    tmp_path: Path, feed_writer: Callable[[list[dict], Path], Path]
) -> None:
    feed = Feed.load(feed_writer(_hidden_counter_frames(), tmp_path / "replay-h.ndjson.gz"), "RACE")
    events = all_events(feed)
    assert [(e.kind, e.te_lo, e.te_hi, e.leader_lap) for e in events] == [("rise", 0, 50, (1, 6))]
    # Lap 3 touches neither end (1 or 6) within one, but sits inside the span.
    w = locate(protest(("7",), laps=(3,)), feed, events)
    assert isinstance(w, Window) and w.event_kind == "rise" and w.contact_te == 50
    # Lap 8 is outside [1, 6] by two: refused. Lap 7 is outside by one: in scope.
    assert locate(protest(("7",), laps=(8,)), feed, events) == Refusal(
        missing_fact=NO_EVENT_LAP, session="S1/RACE"
    )
    assert isinstance(locate(protest(("7",), laps=(7,)), feed, events), Window)


def test_lap_span_uses_the_protest_cars_own_laps(small_feed: Feed) -> None:
    # A made-up event whose leader lap is 9 at both ends but whose car spans laps 5 to 7.
    event = ev.Event(
        kind="rise",
        te_lo=129,
        te_hi=130,
        cars=("4",),
        leader_lap=(9, 9),
        car_laps=(("4", 5, 7),),
        inc_delta=(("4", 2),),
    )
    assert isinstance(locate(protest(("4",), laps=(6,)), small_feed, [event]), Window)
    assert isinstance(locate(protest(("4",), laps=(3,)), small_feed, [event]), Refusal)


def test_last_lap_with_no_leader_lap_refuses_by_name(
    tmp_path: Path, feed_writer: Callable[[list[dict], Path], Path]
) -> None:
    path = feed_writer(_hidden_counter_frames(leader=False), tmp_path / "replay-n.ndjson.gz")
    feed = Feed.load(path, "RACE")
    events = all_events(feed)
    assert locate(protest(("7",), last_lap=True), feed, events) == Refusal(
        missing_fact=NO_LEADER_LAP, session="S1/RACE"
    )
    # With another lap stated as well, that lap is searched on the car's own lap.
    w = locate(protest(("7",), laps=(3,), last_lap=True), feed, events)
    assert isinstance(w, Window) and w.lap is None and w.car_only is False


# ---------------------------------------------------------------- the real reports (private)


@pytest.mark.private
def test_real_reports_locate() -> None:
    """Run the locator on the 10 real reports and print numbers only. Nothing is scored here."""
    if not (RACING / "reports.jsonl").is_file() or not (RACING / "league.json").is_file():
        pytest.skip("private racing data absent")
    from faultline.adapters.pitbot.protest import normalise, read_reports

    league = json.loads((RACING / "league.json").read_text(encoding="utf-8"))
    reports = read_reports(RACING / "reports.jsonl")
    assert len(reports) == 10
    feeds: dict[str, tuple[Feed, list[ev.Event]]] = {}
    for rep in reports:
        sess = league["sessions"][rep["session"]]
        if rep["session"] not in feeds:
            feed = Feed.load(sess["feed"], sess["session"])
            feeds[rep["session"]] = (feed, all_events(feed))
        feed, events = feeds[rep["session"]]
        n = normalise(rep, feed, league["number_map"])
        out = locate(n, feed, events, sess.get("offset_s"), sess.get("offset_error_s"))
        assert locate(n, feed, events, sess.get("offset_s"), sess.get("offset_error_s")) == out
        if isinstance(out, Window):
            lint.assert_clean(out.why, names=list(feed.private_names().values()))
            print(
                f"report {n.id}: te {out.te_lo}-{out.te_hi}, contact_te {out.contact_te}, "
                f"{out.event_kind}, lap {out.lap}, cars {len(n.cars)}"
                f"{' car_only' if out.car_only else ''}"
            )
        else:
            print(f"report {n.id}: refused ({out.missing_fact})")
