"""Tests for the PitBot replay feed reader, on the synthetic feed and (private) one real feed."""

from __future__ import annotations

import copy
import gzip
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from faultline.adapters.pitbot.feed import HOLD_S, TRACK_M, Feed, FeedError
from faultline.roster import closed_set

REPO = Path(__file__).resolve().parents[2]
LEAGUE = REPO / "data" / "racing" / "league.json"
INVENTED = tuple(f"Test Driver {c}" for c in "ABCDEF")

Writer = Callable[[list[dict], Path], Path]


# ---------------------------------------------------------------- load


def test_load_reads_the_session_only(small_feed: Feed) -> None:
    assert small_feed.session == "RACE"
    assert small_feed.track == "Thruxton Circuit"
    assert small_feed.track_m == TRACK_M["Thruxton Circuit"] == 3792.0
    assert small_feed.seconds[0] == 100 and small_feed.seconds[-1] == 160
    assert 90 not in small_feed.seconds  # the QUALIFY frame
    assert 158 not in small_feed.seconds
    assert len(small_feed.seconds) == 60
    assert small_feed.nums == ["1", "2", "3", "4", "5", "6"]
    assert small_feed.cadence_s == 1


def test_load_accepts_plain_ndjson(tmp_path: Path, small_feed_frames: list[dict]) -> None:
    path = tmp_path / "plain.ndjson"
    path.write_text("".join(json.dumps(f) + "\n" for f in small_feed_frames), encoding="utf-8")
    feed = Feed.load(path, "RACE")
    assert len(feed.seconds) == 60
    assert feed.inc("2", 107) == 4


def test_nums_sort_by_numkey(tmp_path: Path, feed_writer: Writer) -> None:
    frame = _frame(10, [("10", 0.1), ("2", 0.2), ("01", 0.3), ("1", 0.4)])
    frame["rows"].append({"num": "x7", "inc": -1, "lap": -1})
    feed = Feed.load(feed_writer([frame], tmp_path / "f.ndjson.gz"), "RACE")
    assert feed.nums == ["01", "1", "2", "10", "x7"]


def test_session_absent_names_present_sessions(small_feed_path: Path) -> None:
    with pytest.raises(FeedError, match=r"no frame for session 'FEATURE'.*QUALIFY, RACE"):
        Feed.load(small_feed_path, "FEATURE")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda fr: fr[1].update(track="Nowhere Raceway"), "tracks"),
        (lambda fr: [f.update(track="Nowhere Raceway") for f in fr], "no length in TRACK_M"),
        (lambda fr: fr[1].update(timeElapsed="soon"), "timeElapsed is not a second"),
        (lambda fr: fr[1].update(timeElapsed=-4), "timeElapsed is not a second"),
        (lambda fr: fr[1]["positions"][0].pop("num"), "no car number"),
        (lambda fr: fr[1]["positions"][0].update(pct=None), "has no pct"),
        (lambda fr: fr[1]["rows"].append("x"), "is not an object"),
    ],
)
def test_bad_frames_are_refused_without_names(
    tmp_path: Path,
    small_feed_frames: list[dict],
    feed_writer: Writer,
    change: Callable[[list[dict]], object],
    reason: str,
) -> None:
    change(small_feed_frames)
    path = feed_writer(small_feed_frames, tmp_path / "bad.ndjson.gz")
    with pytest.raises(FeedError, match=reason) as err:
        Feed.load(path, "RACE")
    assert str(path) in str(err.value)
    assert not any(name in str(err.value) for name in INVENTED)


def test_unreadable_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(FeedError, match="cannot be read"):
        Feed.load(tmp_path / "missing.ndjson.gz", "RACE")
    broken = tmp_path / "broken.ndjson.gz"
    broken.write_bytes(b"\x1f\x8b" + b"not gzip at all")
    with pytest.raises(FeedError, match="gzip data is damaged"):
        Feed.load(broken, "RACE")
    junk = tmp_path / "junk.ndjson"
    junk.write_text('{"session": "RACE"}\n{not json\n', encoding="utf-8")
    with pytest.raises(FeedError, match="line 2 is not JSON"):
        Feed.load(junk, "RACE")
    arr = tmp_path / "arr.ndjson"
    arr.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(FeedError, match="line 1 is not a JSON object"):
        Feed.load(arr, "RACE")


def test_duplicate_second_later_line_wins_car_by_car(tmp_path: Path, feed_writer: Writer) -> None:
    first = _frame(10, [("1", 0.10), ("2", 0.20)], inc={"1": 3, "2": 5})
    second = _frame(10, [("1", 0.11)], inc={"1": -1})
    feed = Feed.load(feed_writer([first, second], tmp_path / "d.ndjson.gz"), "RACE")
    assert feed.seconds == [10]
    assert feed.pct("1", 10) == 0.11
    assert feed.pct("2", 10) == 0.20  # absent from the later frame: the earlier reading stays
    assert feed.inc("1", 10) == 3  # a later -1 never hides a shown counter


def test_negative_pct_is_not_in_the_world(tmp_path: Path, feed_writer: Writer) -> None:
    frames = [_frame(10, [("1", 0.5), ("2", -1.0)]), _frame(11, [("1", 0.51), ("2", 0.3)])]
    feed = Feed.load(feed_writer(frames, tmp_path / "n.ndjson.gz"), "RACE")
    assert feed.pct("2", 10) is None
    assert feed.pit("2", 10) is None
    assert feed.positions_by_te(10, 11) == {10: {"1": 1.5}, 11: {"1": 1.51, "2": 1.3}}


# ---------------------------------------------------------------- per car


def test_counters(small_feed: Feed) -> None:
    assert small_feed.inc("2", 106) == 0 and small_feed.inc("2", 107) == 4
    assert small_feed.inc("3", 107) == 4
    assert small_feed.inc("4", 129) == 0 and small_feed.inc("4", 130) == 2
    assert small_feed.inc("4", 140) == 3
    assert small_feed.inc("5", 120) is None
    assert small_feed.counter_shown("5") is False and small_feed.last_inc("5") is None
    assert small_feed.counter_shown("4") is True and small_feed.last_inc("4") == 3
    assert small_feed.last_inc("1") == 0
    assert small_feed.inc("6", 145) is None  # car 6 is missing from that frame
    assert small_feed.last_inc("99") is None and small_feed.counter_shown("99") is False


def test_pit_cust_and_pct(small_feed: Feed) -> None:
    assert small_feed.pit("4", 149) is False
    assert small_feed.pit("4", 150) is True and small_feed.pit("4", 155) is True
    assert small_feed.pit("4", 156) is False
    assert small_feed.cust_id("3") == 9000003
    assert small_feed.cust_id("99") is None
    assert small_feed.pct("1", 100) == 0.95
    assert small_feed.pct("6", 145) is None
    assert small_feed.pct("99", 100) is None


def test_laps_leader_and_lapped_car(small_feed: Feed) -> None:
    assert small_feed.leader_lap(104) == 3 and small_feed.leader_lap(105) == 4
    assert small_feed.lap("1", 104) == 3 and small_feed.lap("1", 105) == 4
    # The row shows -1 at 120; the shown lap is None but the filled lap carries on.
    assert small_feed.lap("1", 120) is None
    assert small_feed.lap_at("1", 120) == 4
    # Car 6 runs a lap down: its own lap differs from the leader's.
    assert small_feed.lap_at("6", 129) == 2 and small_feed.leader_lap(129) == 4
    assert small_feed.lap_at("6", 130) == 3
    assert small_feed.lap_at("6", 145) is None


def test_lap_at_fills_crossings_between_rows(tmp_path: Path, feed_writer: Writer) -> None:
    # Row lap shown once mid-lap, then never again: crossings carry it.
    frames = [
        _frame(10, [("1", 0.50)], lap={"1": 7}),
        _frame(11, [("1", 0.98)], lap={"1": -1}),
        _frame(12, [("1", 0.03)], lap={"1": -1}),
        # A stale row near the line (still 7) never re-anchors the count.
        _frame(13, [("1", 0.05)], lap={"1": 7}),
        _frame(14, [("1", 0.40)], lap={"1": 8}),
    ]
    feed = Feed.load(feed_writer(frames, tmp_path / "l.ndjson.gz"), "RACE")
    assert [feed.lap_at("1", t) for t in range(10, 15)] == [7, 7, 8, 8, 8]
    assert feed.order_at(13) == ["1"]


def test_lap_at_none_before_any_row(tmp_path: Path, feed_writer: Writer) -> None:
    frames = [_frame(10, [("1", 0.5)], lap={"1": -1}), _frame(11, [("1", 0.6)], lap={"1": 2})]
    feed = Feed.load(feed_writer(frames, tmp_path / "l.ndjson.gz"), "RACE")
    assert feed.lap_at("1", 10) is None and feed.lap_at("1", 11) == 2


# ---------------------------------------------------------------- measures


def test_gap_closes_into_a_collapse(small_feed: Feed) -> None:
    gaps = {t: small_feed.gap_m("3", "2", t) for t in range(100, 108)}
    assert all(g is not None for g in gaps.values())
    assert round(gaps[100], 1) == -19.3  # car 3 behind car 2, closing 3 m a second
    assert abs(gaps[103]) >= 8.0
    assert abs(gaps[106]) <= 2.0
    assert gaps[107] > 0  # car 3 is past
    assert small_feed.gap_m("2", "3", 106) == pytest.approx(-gaps[106])
    assert small_feed.gap_m("3", "99", 106) is None


def test_gap_wraps_across_the_line(tmp_path: Path, feed_writer: Writer) -> None:
    feed = Feed.load(
        feed_writer([_frame(10, [("1", 0.001), ("2", 0.999)])], tmp_path / "w.ndjson.gz"), "RACE"
    )
    assert feed.gap_m("1", "2", 10) == pytest.approx(0.002 * 3792.0)
    assert feed.gap_m("2", "1", 10) == pytest.approx(-0.002 * 3792.0)


def test_speed_shows_the_stall(small_feed: Feed) -> None:
    assert small_feed.speed_mps("2", 100) is None  # no earlier frame
    assert small_feed.speed_mps("2", 106) == pytest.approx(37.92, abs=0.5)
    for t in range(107, 113):
        speed = small_feed.speed_mps("2", t)
        assert speed is not None and speed < 12.0
    assert small_feed.speed_mps("3", 104) == pytest.approx(40.92, abs=0.5)
    assert small_feed.speed_mps("6", 145) is None  # absent
    assert small_feed.speed_mps("6", 146) is None  # previous frame lacks it
    assert small_feed.speed_mps("6", 130) == pytest.approx(37.92, abs=0.5)  # across the line
    assert small_feed.speed_mps("1", 159) == pytest.approx(37.92, abs=0.5)  # 2 s step


def test_speed_needs_a_frame_within_three_seconds(tmp_path: Path, feed_writer: Writer) -> None:
    frames = [_frame(10, [("1", 0.10)]), _frame(14, [("1", 0.14)]), _frame(17, [("1", 0.80)])]
    feed = Feed.load(feed_writer(frames, tmp_path / "s.ndjson.gz"), "RACE")
    assert feed.speed_mps("1", 14) is None  # 4 s step
    assert feed.speed_mps("1", 17) is None  # over half a lap forward in 3 s


def test_order_at_puts_the_leader_first(small_feed: Feed) -> None:
    assert small_feed.order_at(106) == ["1", "2", "3", "4", "5", "6"]
    assert small_feed.order_at(107) == ["1", "3", "2", "4", "5", "6"]
    assert small_feed.order_at(145) == ["1", "3", "2", "4", "5"]
    assert small_feed.order_at(50) == []


def test_order_at_unknown_laps_go_last(tmp_path: Path, feed_writer: Writer) -> None:
    frame = _frame(10, [("1", 0.2), ("2", 0.9), ("3", 0.5)], lap={"1": 5, "2": -1, "3": 5})
    feed = Feed.load(feed_writer([frame], tmp_path / "o.ndjson.gz"), "RACE")
    assert feed.order_at(10) == ["3", "1", "2"]


# ---------------------------------------------------------------- time


def test_second_at_holds_two_seconds(small_feed: Feed) -> None:
    assert small_feed.second_at(99) is None
    assert small_feed.second_at(100) == 100
    assert small_feed.second_at(158) == 157
    assert small_feed.second_at(160 + HOLD_S) == 160
    assert small_feed.second_at(160 + HOLD_S + 1) is None
    assert small_feed.pct("1", 158) == small_feed.pct("1", 157)


def test_two_second_cadence(tmp_path: Path, feed_writer: Writer) -> None:
    frames = [_frame(t, [("1", 0.01 * t)], inc={"1": t // 10}) for t in range(10, 31, 2)]
    feed = Feed.load(feed_writer(frames, tmp_path / "c.ndjson.gz"), "RACE")
    assert feed.cadence_s == 2
    assert feed.pct("1", 13) == feed.pct("1", 12)
    assert feed.inc("1", 21) == 2
    assert feed.speed_mps("1", 13) == pytest.approx(0.01 * 3792.0)
    pos = feed.positions_by_te(11, 15)
    assert sorted(pos) == [12, 14]
    assert pos[12]["1"] == pytest.approx(1.12) and pos[14]["1"] == pytest.approx(1.14)


def test_cadence_rounds_the_mean_step(tmp_path: Path, feed_writer: Writer) -> None:
    # Steps 1, 2, 1, 2: mean 1.5 rounds up to 2 (as on the older feeds).
    frames = [_frame(t, [("1", 0.1)]) for t in (0, 1, 3, 4, 6)]
    assert Feed.load(feed_writer(frames, tmp_path / "a.ndjson.gz"), "RACE").cadence_s == 2
    frames = [_frame(t, [("1", 0.1)]) for t in (0, 1, 2, 4)]
    assert Feed.load(feed_writer(frames, tmp_path / "b.ndjson.gz"), "RACE").cadence_s == 1
    one = [_frame(5, [("1", 0.1)])]
    assert Feed.load(feed_writer(one, tmp_path / "c.ndjson.gz"), "RACE").cadence_s == 1


# ---------------------------------------------------------------- closed set shape


def test_positions_by_te_feeds_the_closed_set(small_feed: Feed) -> None:
    pos = small_feed.positions_by_te(103, 108)
    assert sorted(pos) == list(range(103, 109))
    assert all(isinstance(k, int) for k in pos)
    assert pos[105]["1"] == pytest.approx(4.0)
    assert pos[105]["6"] == pytest.approx(2.75)  # a lap down
    got = closed_set(pos, small_feed.track_m, ["2"], 106, 107, pad_s=1)
    assert [c.num for c in got] == ["2", "3"]
    assert "6" not in small_feed.positions_by_te(145, 145)[145]


# ---------------------------------------------------------------- names


def test_private_names_are_the_only_place_names_live(small_feed: Feed) -> None:
    names = small_feed.private_names()
    assert names == dict(zip(["1", "2", "3", "4", "5", "6"], INVENTED, strict=True))
    held = repr(small_feed) + repr(vars(small_feed))
    assert not any(name in held for name in INVENTED)
    assert not any("Driver" in key for key in vars(small_feed))


def test_private_names_read_rows_and_positions(tmp_path: Path, feed_writer: Writer) -> None:
    frame = _frame(10, [("1", 0.1), ("2", 0.2)])
    frame["positions"][0]["name"] = "Test Driver A"
    frame["rows"][1]["name"] = "Test Driver B"
    feed = Feed.load(feed_writer([frame], tmp_path / "p.ndjson.gz"), "RACE")
    assert feed.private_names() == {"1": "Test Driver A", "2": "Test Driver B"}


def test_load_is_deterministic(small_feed_path: Path) -> None:
    a, b = Feed.load(small_feed_path, "RACE"), Feed.load(small_feed_path, "RACE")
    assert a.positions_by_te(0, 999) == b.positions_by_te(0, 999)
    assert [a.order_at(t) for t in a.seconds] == [b.order_at(t) for t in b.seconds]


def test_fixture_frames_are_not_shared(small_feed_frames: list[dict]) -> None:
    copied = copy.deepcopy(small_feed_frames)
    assert copied == small_feed_frames and len(copied) == 61


# ---------------------------------------------------------------- private corpus


@pytest.mark.private
def test_one_real_feed_loads() -> None:
    if not LEAGUE.is_file():
        pytest.skip("private corpus absent (data/racing/league.json not found)")
    league = json.loads(LEAGUE.read_text(encoding="utf-8"))
    sessions = league["sessions"]
    key = sorted(sessions)[0]
    cfg = sessions[key]
    if not Path(cfg["feed"]).is_file():
        pytest.skip("private corpus absent (the session's feed file is not on this machine)")
    feed = Feed.load(cfg["feed"], cfg["session"])
    with gzip.open(cfg["feed"], "rt", encoding="utf-8") as fh:
        frames = sum(1 for line in fh if line.strip() and json.loads(line).get("session"))
    assert len(feed.seconds) > 100
    assert len(feed.seconds) <= frames
    assert len(feed.nums) == cfg["cars"]
    assert feed.track_m in TRACK_M.values()
    assert feed.cadence_s in (1, 2)
    assert sum(1 for n in feed.nums if feed.counter_shown(n)) == (
        len(feed.nums) if cfg["counter_shown"] else 0
    )
    assert len(feed.private_names()) == len(feed.nums)


# ---------------------------------------------------------------- helpers


def _frame(
    te: int,
    cars: list[tuple[str, float]],
    inc: dict[str, int] | None = None,
    lap: dict[str, int] | None = None,
) -> dict:
    """A minimal RACE frame at Thruxton: positions and rows, no names unless a test adds one."""
    inc = inc or {}
    lap = lap or {}
    return {
        "timeElapsed": te,
        "session": "RACE",
        "track": "Thruxton Circuit",
        "leaderLap": 1,
        "positions": [
            {"num": n, "pct": p, "pos": i, "pit": False, "carIdx": i, "custId": 100 + i}
            for i, (n, p) in enumerate(cars, start=1)
        ],
        "rows": [{"num": n, "inc": inc.get(n, 0), "lap": lap.get(n, 1)} for n, _p in cars],
    }
