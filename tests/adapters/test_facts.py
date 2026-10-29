"""Tests for the blame-neutral fact sheet: the synthetic feed, a 2 s feed, refusals, a
fault-word and lint sweep over every sentence, and (private) the same sweep on real windows."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from faultline import lint
from faultline.adapters.pitbot.events import Event, collapses, paired_plus4, rises
from faultline.adapters.pitbot.facts import NO_CONTACT_SENTENCE, FactsError, facts
from faultline.adapters.pitbot.feed import Feed
from faultline.roster import closed_set

REPO = Path(__file__).resolve().parents[2]
LEAGUE = REPO / "data" / "racing" / "league.json"

Writer = Callable[[list[dict], Path], Path]

FAULT_WORDS = (
    "fault",
    "faults",
    "at fault",
    "caused",
    "cause",
    "causing",
    "blame",
    "blamed",
    "dive",
    "dived",
    "careless",
    "responsible",
    "responsibility",
    "penalty",
    "should",
    "no action",
    "racing incident",
    "because",
)
_FAULT = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in FAULT_WORDS) + r")\b", re.I)


def _events(feed: Feed) -> list[Event]:
    r = rises(feed)
    return r + paired_plus4(feed, r) + collapses(feed, r)


def _assert_neutral(sentences: list[str]) -> None:
    assert sentences
    for s in sentences:
        assert not _FAULT.search(s), s
        assert "/" not in s and "\\" not in s, s
        lint.assert_clean(s, names=[])
        assert s.endswith("."), s


def _pair_window(feed: Feed) -> list[str]:
    return facts(feed, _events(feed), ["2", "3", "4"], 103, 109, 107)


def _measured(sentences: list[str]) -> list[str]:
    fixed = (NO_CONTACT_SENTENCE, "The feed never shows")
    return [s for s in sentences if not s.startswith(fixed)]


# ---------------------------------------------------------------- the synthetic feed


def test_contact_pair_sentence(small_feed: Feed) -> None:
    out = _pair_window(small_feed)
    assert out[0] == (
        "The feed registered a contact pair between car 2 and car 3 between second 106 and "
        "second 107, to the nearest second: both incident counters rose by 4 or more, and the "
        "two cars were 1.5 metres apart at the closest."
    )
    assert out[1] == NO_CONTACT_SENTENCE
    # The +4 steps are stated once, in the pair sentence, not again as rises.
    assert not any("rose by 4," in s or s.startswith("The incident counter of car 2") for s in out)


def test_order_closing_and_stall(small_feed: Feed) -> None:
    out = _pair_window(small_feed)
    assert (
        "At second 104, 3 seconds before second 107, the race order of these cars was "
        "car 2, car 3, car 4, to the nearest second."
    ) in out
    assert (
        "At second 106, 1 second before second 107, the race order of these cars was "
        "car 2, car 3, car 4, to the nearest second."
    ) in out
    assert (
        "At second 106, the two closest of these cars were car 3, 1.5 metres behind car 2, "
        "and since second 105 the gap closed at 3.0 metres a second, to the nearest second."
    ) in out
    stall = [s for s in out if s.startswith("Car 2 moved under 12.0 metres a second")]
    assert stall == [
        "Car 2 moved under 12.0 metres a second between second 107 and second 112, "
        "lowest 5.7 metres a second, to the nearest second."
    ]
    assert not any(s.startswith("Car 3 moved under") for s in out)


def test_positions_by_lap_end(small_feed: Feed) -> None:
    out = _pair_window(small_feed)
    assert any(
        s.startswith("Car 2 ran in position 2 at second 106") and "1 position lost" in s
        for s in out
    )
    assert any(
        s.startswith("Car 3 ran in position 3 at second 106") and "1 position gained" in s
        for s in out
    )
    assert any(s.startswith("Car 4 ran in position 4") and "the same position" in s for s in out)


def test_fixed_order_of_sections(small_feed: Feed) -> None:
    out = _pair_window(small_feed)
    first = [
        next(i for i, s in enumerate(out) if s.startswith(p))
        for p in (
            "The feed registered",
            NO_CONTACT_SENTENCE,
            "The incident counter",
            "Car 2 moved under",
            "At second 104",
            "At second 106, 1 second",
            "At second 106, the two closest",
            "Car 2 ran in position",
        )
    ]
    assert first == sorted(first)


def test_plus2_and_plus1_on_car_4(small_feed: Feed) -> None:
    out = facts(small_feed, _events(small_feed), ["4", "5", "6"], 125, 145, 131)
    assert out[0] == (
        "The feed registered no contact pair among these cars between second 125 and "
        "second 145, to the nearest second."
    )
    assert out[1] == NO_CONTACT_SENTENCE
    assert (
        "The incident counter of car 4 rose by 2, the step for loss of control, between "
        "second 129 and second 130, to the nearest second."
    ) in out
    assert (
        "The incident counter of car 4 rose by 1, the step for off track, between second 139 "
        "and second 140, to the nearest second."
    ) in out
    assert (
        "The feed never shows the incident counter of car 5, so no step can be read there." in out
    )


def test_pit_road(small_feed: Feed) -> None:
    out = facts(small_feed, _events(small_feed), ["4"], 148, 156, 152)
    assert any(s.startswith("Car 4 was on pit road between second 150 and second 155") for s in out)
    assert not any(s.startswith("Car 4 moved under") for s in out)


def test_only_the_closed_set(small_feed: Feed) -> None:
    out = facts(small_feed, _events(small_feed), ["2", "4"], 103, 109, 107)
    # The pair holds car 3, outside the set: no pair sentence and no car 3 anywhere.
    assert out[0].startswith("The feed registered no contact pair")
    assert not any(re.search(r"\bcar 3\b", s, re.I) for s in out)
    assert not any(re.search(r"\bcar 1\b", s, re.I) for s in out)


def test_deterministic(small_feed: Feed) -> None:
    assert _pair_window(small_feed) == _pair_window(small_feed)
    shuffled = list(reversed(_events(small_feed)))
    assert facts(small_feed, shuffled, ["4", "3", "2"], 103, 109, 107) == _pair_window(small_feed)


def test_resolution_on_a_1s_feed(small_feed: Feed) -> None:
    for s in _measured(_pair_window(small_feed)):
        assert s.endswith("to the nearest second.") or "to the nearest second:" in s, s


def test_resolution_on_a_2s_feed(
    tmp_path: Path, small_feed_frames: list[dict], feed_writer: Writer
) -> None:
    frames = [f for f in small_feed_frames if f.get("timeElapsed", 1) % 2 == 0]
    feed = Feed.load(feed_writer(frames, tmp_path / "two.ndjson.gz"), "RACE")
    assert feed.cadence_s == 2
    out = facts(feed, _events(feed), ["2", "3", "4"], 103, 110, 108)
    assert out[1] == NO_CONTACT_SENTENCE
    assert out[0].startswith("The feed registered a contact pair between car 2 and car 3")
    measured = _measured(out)
    assert measured
    for s in measured:
        assert "to the nearest 2 seconds" in s, s
        assert "to the nearest second" not in s, s
    _assert_neutral(out)


def test_fixed_sentence_always_present(small_feed: Feed) -> None:
    for cars, lo, hi, c in (
        (["1"], 100, 101, 101),
        (["2", "3"], 103, 109, 107),
        (["5"], 140, 150, 145),
        (["6"], 140, 160, 150),
    ):
        out = facts(small_feed, _events(small_feed), cars, lo, hi, c)
        assert out.count(NO_CONTACT_SENTENCE) == 1


def test_events_without_rises_say_none(small_feed: Feed) -> None:
    out = facts(small_feed, [], ["2", "3"], 103, 109, 107)
    assert out[0].startswith("The feed registered no contact pair")
    assert out[1] == NO_CONTACT_SENTENCE


@pytest.mark.parametrize(
    ("cars", "lo", "hi"),
    [([], 100, 110), (["99"], 100, 110), (["2"], 110, 100)],
)
def test_refusals(small_feed: Feed, cars: list[str], lo: int, hi: int) -> None:
    with pytest.raises(FactsError):
        facts(small_feed, [], cars, lo, hi, 105)


def test_sweep_every_fixture_window(small_feed: Feed) -> None:
    events = _events(small_feed)
    every = small_feed.nums
    count = 0
    for lo in range(95, 165, 5):
        for width in (0, 4, 12):
            for contact in (lo, lo + width):
                for cars in (every, ["2", "3"], ["4"], ["5", "6"]):
                    out = facts(small_feed, events, cars, lo, lo + width, contact)
                    _assert_neutral(out)
                    assert out.count(NO_CONTACT_SENTENCE) == 1
                    count += len(out)
    assert count > 500


def test_sweep_catches_a_fault_word() -> None:
    assert _FAULT.search("Car 2 was at fault.")
    assert _FAULT.search("The contact CAUSED a spin.")
    assert not _FAULT.search("Car 2 moved under 12.0 metres a second.")


# ---------------------------------------------------------------- private corpus


@pytest.mark.private
def test_private_real_windows_are_neutral() -> None:
    if not LEAGUE.exists():
        pytest.skip("private corpus absent: data/racing/league.json is not on this machine")
    sessions = json.loads(LEAGUE.read_text(encoding="utf-8"))["sessions"]
    windows = sentences = 0
    two_second = 0
    for _key, s in sorted(sessions.items()):
        feed = Feed.load(s["feed"], s["session"])
        events = _events(feed)
        pairs = [e for e in events if e.kind == "paired_plus4"][:3]
        for pair in pairs:
            lo, hi = pair.te_lo - 3, pair.te_hi + 2
            cands = closed_set(
                feed.positions_by_te(lo - 3, hi + 3), feed.track_m, pair.cars, lo, hi
            )
            cars = sorted({c.num for c in cands} | set(pair.cars))
            out = facts(feed, events, cars, lo, hi, pair.te_hi)
            _assert_neutral(out)
            assert out.count(NO_CONTACT_SENTENCE) == 1
            assert out[0].startswith("The feed registered a contact pair")
            res = (
                "to the nearest second"
                if feed.cadence_s == 1
                else f"to the nearest {feed.cadence_s} seconds"
            )
            assert all(res in m for m in _measured(out))
            two_second += feed.cadence_s == 2
            windows += 1
            sentences += len(out)
    print(f"real windows: {windows}, sentences: {sentences}, on 2 s feeds: {two_second}")
    assert windows >= 10
