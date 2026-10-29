"""Tests for the entry roster, closed set and digit snapping in `faultline.roster`."""

from __future__ import annotations

import dataclasses

import pytest

from faultline.roster import (
    WHY_FOCUS,
    WHY_NEAR,
    Candidate,
    Entry,
    RosterError,
    closed_set,
    numkey,
    snap,
)

LOOP_M = 1000.0  # 1 m is 0.001 of a loop


def steady(start: dict[str, float], step: float, te_from: int, te_to: int) -> dict:
    """Every subject moves `step` of a loop per second from its start progress."""
    return {
        te: {num: p + step * (te - te_from) for num, p in start.items()}
        for te in range(te_from, te_to + 1)
    }


# --- Entry and numkey --------------------------------------------------------


def test_entry_is_frozen() -> None:
    entry = Entry("01", 12345, "899")
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.num = "1"  # type: ignore[misc]
    assert Entry("7", 1).league_num is None


def test_numkey_sorts_digits_by_int_then_string_then_others() -> None:
    nums = ["x9", "10", "01", "2", "1", "A", "001"]
    assert sorted(nums, key=numkey) == ["001", "01", "1", "2", "10", "A", "x9"]


def test_numkey_keeps_01_and_1_distinct() -> None:
    assert numkey("01") != numkey("1")


# --- closed_set --------------------------------------------------------------


def test_near_subject_joins_and_far_subject_does_not() -> None:
    positions = steady({"5": 3.500, "9": 3.505, "40": 3.600}, 0.01, 95, 115)
    out = closed_set(positions, LOOP_M, ["5"], 100, 110)
    assert [c.num for c in out] == ["5", "9"]
    focus, near = out
    assert focus == Candidate("5", 5.0, "focus", WHY_FOCUS)
    assert near == Candidate("9", 5.0, "ahead", WHY_NEAR)


def test_behind_relation_and_closest_moment() -> None:
    # subject 3 closes on focus 5 from 20 m behind, closest 2 m at second 109, then falls back
    positions: dict[int, dict[str, float]] = {}
    for te in range(90, 120):
        gap_m = 2.0 + abs(te - 109) * 2.0
        positions[te] = {"5": 2.0 + te * 0.01, "3": 2.0 + te * 0.01 - gap_m / LOOP_M}
    out = closed_set(positions, LOOP_M, ["5"], 100, 110)
    near = next(c for c in out if c.num == "3")
    assert near.relation == "behind"
    assert near.closest_m == 2.0
    assert near.why == WHY_NEAR


def test_pad_extends_the_window() -> None:
    # subject 8 is near only at second 112, two seconds past te_hi
    positions = steady({"5": 1.0, "8": 1.2}, 0.0, 95, 115)
    positions[112] = {"5": 1.0, "8": 1.004}
    assert [c.num for c in closed_set(positions, LOOP_M, ["5"], 100, 110)] == ["5", "8"]
    assert [c.num for c in closed_set(positions, LOOP_M, ["5"], 100, 110, pad_s=1)] == ["5"]


def test_near_m_is_inclusive_and_configurable() -> None:
    # a 1024 m loop keeps 8 m and 12.5 m exact in binary fractions
    positions = {100: {"5": 0.5, "6": 0.5 + 8 / 1024, "7": 0.5 - 12.5 / 1024}}
    assert [c.num for c in closed_set(positions, 1024.0, ["5"], 100, 100)] == ["5", "6"]
    wide = closed_set(positions, 1024.0, ["5"], 100, 100, near_m=12.5)
    assert [c.num for c in wide] == ["5", "6", "7"]


def test_distance_wraps_round_the_loop_and_ignores_whole_loops() -> None:
    # focus just past the line, other just before it and one full loop down
    positions = {100: {"5": 7.001, "6": 5.997}}
    out = closed_set(positions, LOOP_M, ["5"], 100, 100)
    near = next(c for c in out if c.num == "6")
    assert near.closest_m == 4.0
    assert near.relation == "behind"


def test_relation_is_to_the_nearest_focus_subject() -> None:
    positions = {100: {"5": 0.100, "6": 0.120, "9": 0.114}}
    out = {c.num: c for c in closed_set(positions, LOOP_M, ["5", "6"], 100, 100)}
    assert out["9"].relation == "behind"  # 6 m behind 6, 14 m ahead of 5
    assert out["9"].closest_m == 6.0
    assert out["5"].relation == out["6"].relation == "focus"
    assert out["5"].closest_m == 14.0
    assert out["6"].closest_m == 6.0


def test_level_relation_at_zero_gap() -> None:
    out = closed_set({100: {"5": 0.3, "6": 0.3}}, LOOP_M, ["5"], 100, 100)
    assert out[1] == Candidate("6", 0.0, "level", WHY_NEAR)


def test_focus_alone_has_no_gap_and_missing_focus_is_left_out() -> None:
    out = closed_set({100: {"5": 0.3}}, LOOP_M, ["5", "77"], 100, 100)
    assert out == [Candidate("5", None, "focus", WHY_FOCUS)]
    assert closed_set({100: {"6": 0.3}}, LOOP_M, ["5"], 100, 100) == []


def test_missing_seconds_are_skipped() -> None:
    assert closed_set({}, LOOP_M, ["5"], 100, 110) == []


def test_output_sorted_by_numkey_with_01_and_1_distinct() -> None:
    positions = {100: {"10": 0.5, "1": 0.501, "01": 0.502, "2": 0.499, "A": 0.5005}}
    out = closed_set(positions, LOOP_M, ["10"], 100, 100)
    assert [c.num for c in out] == ["01", "1", "2", "10", "A"]


def test_closest_m_is_rounded_to_one_decimal() -> None:
    out = closed_set({100: {"5": 0.0, "6": 0.00123456}}, LOOP_M, ["5"], 100, 100)
    assert out[1].closest_m == 1.2


def test_closed_set_is_deterministic() -> None:
    positions = steady({"5": 3.5, "9": 3.505, "12": 3.497, "40": 3.6}, 0.01, 90, 120)
    first = closed_set(positions, LOOP_M, ["5", "9"], 100, 110)
    assert first == closed_set(
        dict(reversed(list(positions.items()))), LOOP_M, ["9", "5"], 100, 110
    )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"track_m": 0.0}, "loop length"),
        ({"track_m": float("nan")}, "loop length"),
        ({"te_lo": 110, "te_hi": 100}, "window ends before it starts"),
        ({"near_m": -1.0}, "reach"),
        ({"pad_s": -1}, "pad"),
        ({"focus": []}, "no focus subject"),
    ],
)
def test_bad_input_is_refused_with_its_reason(kwargs: dict, reason: str) -> None:
    args: dict = {
        "positions_by_te": {100: {"5": 0.1}},
        "track_m": LOOP_M,
        "focus": ["5"],
        "te_lo": 100,
        "te_hi": 100,
    }
    args.update(kwargs)
    with pytest.raises(RosterError, match=reason):
        closed_set(**args)


def test_non_finite_progress_is_refused() -> None:
    with pytest.raises(RosterError, match="subject 6: progress is not finite"):
        closed_set({100: {"5": 0.1, "6": float("inf")}}, LOOP_M, ["5"], 100, 100)


# --- snap --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("read", "candidates", "expected"),
    [
        # the logged misreads, the camera subject left out for reads of the other subject
        ("559", ["959", "70", "32"], "959"),
        ("999", ["959", "70", "32"], "959"),
        ("355", ["555", "959", "70"], "555"),
        ("81", ["01", "44", "7"], "01"),
    ],
)
def test_logged_misreads_snap_right(read: str, candidates: list[str], expected: str) -> None:
    assert snap(read, candidates) == expected


def test_tie_is_refused() -> None:
    # with 555 left in the set, 559 is one edit from both 555 and 959
    assert snap("559", ["555", "959"]) is None


def test_distance_over_one_is_refused() -> None:
    assert snap("123", ["959", "70"]) is None


def test_exact_match_wins_over_a_distance_one_neighbour() -> None:
    assert snap("1", ["01", "1"]) == "1"
    assert snap("01", ["01", "1"]) == "01"


def test_snap_accepts_candidates_and_ignores_non_digits_in_read() -> None:
    cands = [Candidate("959", 2.0, "ahead", WHY_NEAR), Candidate("70", 0.5, "focus", WHY_FOCUS)]
    assert snap("#999", cands) == "959"
    assert snap("no digits", cands) is None
    assert snap("959", []) is None


def test_single_digit_read_never_snaps_by_one_edit() -> None:
    assert snap("7", ["3", "42"]) is None
    assert snap("1", ["12"]) is None
    assert snap("7", ["7", "42"]) == "7"


def test_read_matching_a_roster_entry_outside_the_set_is_refused() -> None:
    roster = ["01", "44", "7", "81"]
    assert snap("81", ["01", "44", "7"], roster) is None
    entries = [Entry("01", 1), Entry("44", 2), Entry("7", 3), Entry("81", 4)]
    assert snap("81", ["01", "44", "7"], entries) is None


def test_roster_without_the_read_still_snaps() -> None:
    roster = ["01", "44", "7", "959", "70", "32", "555"]
    assert snap("81", ["01", "44", "7"], roster) == "01"
    assert snap("559", ["959", "70", "32"], roster) == "959"
    assert snap("999", ["959", "70", "32"], roster) == "959"
    assert snap("355", ["555", "959", "70"], roster) == "555"
    assert snap("959", ["959", "70"], roster) == "959"


def test_string_second_keys_are_refused() -> None:
    with pytest.raises(RosterError, match="'10'"):
        closed_set({"10": {"5": 0.1}}, LOOP_M, ["5"], 10, 10)  # type: ignore[dict-item]


def test_negative_progress_is_refused() -> None:
    with pytest.raises(RosterError, match="second 100, subject 6: progress is negative"):
        closed_set({100: {"5": 0.1, "6": -1}}, LOOP_M, ["5"], 100, 100)
