"""Tests for the feed events: the synthetic feed, plus (private) a contract-drift check against
the 28 Oct catalogue on the 11 corpus sessions."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from faultline.adapters.pitbot import events as ev
from faultline.adapters.pitbot.events import Event, all_events, collapses, paired_plus4, rises
from faultline.adapters.pitbot.feed import Feed
from faultline.roster import numkey

REPO = Path(__file__).resolve().parents[2]
LEAGUE = REPO / "data" / "racing" / "league.json"
CATALOGUE = Path(
    "C:/glitch/workspaces/ai-steward/experiments/2026-10-28-phoenix-catalogue/scripts/catalogue.py"
)

Writer = Callable[[list[dict], Path], Path]


def _frame(frames: list[dict], te: int) -> dict:
    return next(f for f in frames if f.get("timeElapsed") == te and f.get("session") == "RACE")


def _row(frame: dict, num: str) -> dict:
    return next(r for r in frame["rows"] if r["num"] == num)


def _pos(frame: dict, num: str) -> dict:
    return next(p for p in frame["positions"] if p["num"] == num)


# ---------------------------------------------------------------- thresholds


def test_thresholds_are_the_pre_registered_ones() -> None:
    assert (ev.COLLAPSE_FROM_M, ev.COLLAPSE_TO_M) == (8.0, 2.0)
    assert (ev.COLLAPSE_WITHIN_S, ev.COLLAPSE_MERGE_S) == (3, 10)
    assert (ev.STALL_MPS, ev.STALL_AFTER_S) == (12.0, 5)
    assert ev.RISE_WINDOW == (-2, 5)
    assert ev.PAIR_NEAR_M == 8.0
    assert ev.PAIR_DELTA == 4


# ---------------------------------------------------------------- rises


def test_rises_on_the_synthetic_feed(small_feed: Feed) -> None:
    got = [(e.cars, e.te_lo, e.te_hi, e.inc_delta) for e in rises(small_feed)]
    assert got == [
        (("2",), 106, 107, (("2", 4),)),
        (("3",), 106, 107, (("3", 4),)),
        (("4",), 129, 130, (("4", 2),)),
        (("4",), 139, 140, (("4", 1),)),
    ]


def test_the_plus_two_rise_on_car_4(small_feed: Feed) -> None:
    (rise,) = [e for e in rises(small_feed) if e.cars == ("4",) and e.inc_delta[0][1] == 2]
    assert rise.kind == "rise"
    assert (rise.te_lo, rise.te_hi) == (129, 130)
    assert rise.leader_lap == (4, 4)
    assert rise.car_laps == (("4", 3, 3),)
    assert rise.closest_m is None and not rise.stall and not rise.rise


def test_a_never_shown_counter_gives_nothing(small_feed: Feed) -> None:
    every = rises(small_feed) + paired_plus4(small_feed) + collapses(small_feed)
    assert all("5" not in e.cars for e in every)


def test_an_intermittent_counter_widens_the_bounds(
    tmp_path: Path, small_feed_frames: list[dict], feed_writer: Writer
) -> None:
    for te in range(120, 130):
        _row(_frame(small_feed_frames, te), "4")["inc"] = -1
    feed = Feed.load(feed_writer(small_feed_frames, tmp_path / "f.ndjson.gz"), "RACE")
    (rise,) = [e for e in rises(feed) if e.cars == ("4",) and e.inc_delta == (("4", 2),)]
    assert (rise.te_lo, rise.te_hi) == (119, 130)


def test_a_repeated_second_reads_the_later_line(
    tmp_path: Path, small_feed_frames: list[dict], feed_writer: Writer
) -> None:
    # A second line at 135 shows car 4 on 5: the later line wins (2 -> 5 at 135); back to 2 at 136,
    # so the next step up is 2 -> 3 at 140 again.
    extra = json.loads(json.dumps(_frame(small_feed_frames, 135)))
    _row(extra, "4")["inc"] = 5
    at = small_feed_frames.index(_frame(small_feed_frames, 135)) + 1
    small_feed_frames.insert(at, extra)
    feed = Feed.load(feed_writer(small_feed_frames, tmp_path / "f.ndjson.gz"), "RACE")
    car4 = [(e.te_lo, e.te_hi, e.inc_delta[0][1]) for e in rises(feed) if e.cars == ("4",)]
    assert car4 == [(129, 130, 2), (134, 135, 3), (139, 140, 1)]


# ---------------------------------------------------------------- paired +4


def test_the_pair_at_106_107(small_feed: Feed) -> None:
    (pair,) = paired_plus4(small_feed)
    assert pair.kind == "paired_plus4"
    assert pair.cars == ("2", "3")
    assert (pair.te_lo, pair.te_hi) == (106, 107)
    assert pair.closest_m == 1.5
    assert pair.inc_delta == (("2", 4), ("3", 4))
    assert pair.leader_lap == (4, 4)
    assert pair.car_laps == (("2", 3, 3), ("3", 3, 3))


def test_no_pair_when_the_cars_are_apart(
    tmp_path: Path, small_feed_frames: list[dict], feed_writer: Writer
) -> None:
    for te in (106, 107):
        _pos(_frame(small_feed_frames, te), "3")["pct"] = 0.5
    feed = Feed.load(feed_writer(small_feed_frames, tmp_path / "f.ndjson.gz"), "RACE")
    assert paired_plus4(feed) == []


def test_pair_takes_the_given_rises(small_feed: Feed) -> None:
    assert paired_plus4(small_feed, rises(small_feed)) == paired_plus4(small_feed)
    assert paired_plus4(small_feed, []) == []


# ---------------------------------------------------------------- collapses


def test_the_collapse_with_stall_and_rise(small_feed: Feed) -> None:
    (col,) = collapses(small_feed)
    assert col.kind == "collapse"
    assert col.cars == ("2", "3")
    assert (col.te_lo, col.te_hi) == (106, 106)
    assert col.closest_m == 1.5
    assert col.from_m == 10.6
    assert col.stall_cars == ("2",) and col.stall is True
    assert col.rise_cars == ("2", "3") and col.rise is True
    assert col.inc_delta == ()


def test_collapse_rise_flag_needs_a_rise(small_feed: Feed) -> None:
    (col,) = collapses(small_feed, [])
    assert col.rise is False and col.rise_cars == ()
    assert col.stall is True


def test_a_car_on_pit_road_never_collapses(
    tmp_path: Path, small_feed_frames: list[dict], feed_writer: Writer
) -> None:
    _pos(_frame(small_feed_frames, 106), "3")["pit"] = True
    feed = Feed.load(feed_writer(small_feed_frames, tmp_path / "f.ndjson.gz"), "RACE")
    assert collapses(feed) == []


def test_a_slow_close_is_no_collapse(
    tmp_path: Path, small_feed_frames: list[dict], feed_writer: Writer
) -> None:
    # Car 3 already within 8 m from 103 on: no wide gap in the 3 s before 106.
    _pos(_frame(small_feed_frames, 103), "3")["pct"] = 0.828
    feed = Feed.load(feed_writer(small_feed_frames, tmp_path / "f.ndjson.gz"), "RACE")
    assert collapses(feed) == []


# ---------------------------------------------------------------- shape


def test_events_are_frozen_sorted_and_hold_no_name(small_feed: Feed) -> None:
    every = rises(small_feed) + paired_plus4(small_feed) + collapses(small_feed)
    for event in every:
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.te_lo = 0  # type: ignore[misc]
        assert list(event.cars) == sorted(event.cars, key=numkey)
        assert "Test Driver" not in repr(event)
    for got in (rises(small_feed), paired_plus4(small_feed), collapses(small_feed)):
        keys = [(e.te_lo, e.kind, tuple(numkey(c) for c in e.cars)) for e in got]
        assert keys == sorted(keys)


def test_events_are_deterministic(small_feed_path: Path) -> None:
    a, b = Feed.load(small_feed_path, "RACE"), Feed.load(small_feed_path, "RACE")
    assert collapses(a) == collapses(b)
    assert paired_plus4(a) == paired_plus4(b)


def test_all_events_is_the_three_lists_in_one(small_feed: Feed) -> None:
    combined = all_events(small_feed)
    parts = rises(small_feed) + paired_plus4(small_feed) + collapses(small_feed)
    assert sorted(combined, key=repr) == sorted(parts, key=repr)
    assert [(e.te_lo, e.kind, e.cars) for e in combined] == [
        (106, "collapse", ("2", "3")),
        (106, "paired_plus4", ("2", "3")),
        (106, "rise", ("2",)),
        (106, "rise", ("3",)),
        (129, "rise", ("4",)),
        (139, "rise", ("4",)),
    ]


# ---------------------------------------------------------------- contract drift (private)


def _load_catalogue() -> ModuleType:
    """The catalogue module, read-only from ai-steward: no bytecode written, sys.path restored."""
    path_before, bytecode_before = list(sys.path), sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("_faultline_drift_catalogue", CATALOGUE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = path_before
        sys.dont_write_bytecode = bytecode_before


def _catalogue_lookback_max(fd: Any, pair: tuple[str, str], te: int) -> float | None:
    """The catalogue's own look-back: the three previous frame LINES, not seconds."""
    tes: list[int] = fd.tes
    i = tes.index(te)
    gaps = [
        abs(g)
        for t in tes[max(0, i - ev.COLLAPSE_WITHIN_S) : i]
        if te - t <= ev.COLLAPSE_WITHIN_S and (g := fd.gap(*pair, t)) is not None
    ]
    return max(gaps) if gaps else None


@pytest.mark.private
def test_contract_drift_against_the_catalogue() -> None:
    if not LEAGUE.exists():
        pytest.skip("private corpus absent: data/racing/league.json is not on this machine")
    if not CATALOGUE.exists():
        pytest.skip("ai-steward catalogue.py absent: the drift reference is not on this machine")
    cat = _load_catalogue()
    sessions = json.loads(LEAGUE.read_text(encoding="utf-8"))["sessions"]
    assert len(sessions) == 11

    pairs_total = cat_collapses_total = explained_total = 0
    for key, s in sorted(sessions.items()):
        fd = cat.Feed(s["subsession"], s["session"])
        cat_rises = cat.rises(fd)
        cat_pairs = cat.paired_plus4(fd, cat_rises)
        cat_cols = cat.collapses(fd, cat_rises)

        feed = Feed.load(s["feed"], s["session"])
        ours_rises = rises(feed)
        ours_pairs = paired_plus4(feed, ours_rises)
        ours_cols = collapses(feed, ours_rises)

        # Rises and paired +4: the same events, bounds and closest gap.
        assert len(ours_rises) == len(cat_rises), key
        assert sorted(
            (e.cars[0], e.te_lo, e.te_hi, e.inc_delta[0][1]) for e in ours_rises
        ) == sorted((r["car"], *r["te_bounds"], r["delta"]) for r in cat_rises), key
        assert sorted((e.cars, e.te_lo, e.te_hi, e.closest_m) for e in ours_pairs) == sorted(
            (tuple(e["cars"]), *e["te_bounds"], e["closest_m"]) for e in cat_pairs
        ), key
        pairs_total += len(ours_pairs)

        # Collapses: every catalogue collapse is ours, with the same flags.
        theirs = {
            (tuple(e["cars"]), *e["te_bounds"]): (bool(e["stall"]), bool(e["inc_rise"]))
            for e in cat_cols
        }
        ours: dict[tuple, Event] = {(e.cars, e.te_lo, e.te_hi): e for e in ours_cols}
        assert len(ours) == len(ours_cols) and len(theirs) == len(cat_cols), key
        for k, flags in theirs.items():
            assert k in ours, (key, k)
            assert (ours[k].stall, ours[k].rise) == flags, (key, k)

        # Any extra collapse of ours is the repeated-second look-back, and nothing else: the
        # catalogue's three previous lines miss the wide gap that faultline's three seconds see.
        for k, event in ours.items():
            if k in theirs:
                continue
            pair, te = event.cars, event.te_lo
            assert event.te_hi == te, (key, k)
            assert len(fd.tes) != len(set(fd.tes)), (key, k, "no repeated second in this session")
            line_max = _catalogue_lookback_max(fd, (pair[0], pair[1]), te)
            assert line_max is None or line_max < ev.COLLAPSE_FROM_M, (key, k)
            assert event.from_m is not None and event.from_m >= ev.COLLAPSE_FROM_M, (key, k)
            explained_total += 1

        extra = len(ours.keys() - theirs.keys())
        assert len(ours_cols) - extra == len(cat_cols), key
        cat_collapses_total += len(cat_cols)

    assert pairs_total == 100
    assert cat_collapses_total == 501
    assert explained_total == 3
