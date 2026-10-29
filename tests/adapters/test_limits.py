"""Tests for the incident-limit rulings (`faultline.adapters.pitbot.limits`).

Unit tests run on the synthetic fixture and small hand-made feeds. The private score test runs
on the real league data and reproduces rule A of the 29 Oct racing telemetry judge, read in
place from ai-steward (never written into); it prints counts only.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from faultline.adapters.pitbot.feed import Feed
from faultline.adapters.pitbot.limits import (
    MISSING_COUNTER,
    LimitsError,
    incident_limit,
    limits_for_league,
)
from faultline.lint import assert_clean
from faultline.roster import numkey

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = ROOT / "data" / "racing" / "league.json"
AI_STEWARD = Path("C:/glitch/workspaces/ai-steward")
JUDGE = AI_STEWARD / "experiments/2026-10-29-racing-telemetry-judge/scripts/judge.py"
JUDGE_LOG = AI_STEWARD / "experiments/2026-10-29-racing-telemetry-judge/LOG.md"
CATALOGUE_PY = AI_STEWARD / "experiments/2026-10-28-phoenix-catalogue/scripts/catalogue.py"
CATALOGUE_JSON = (
    AI_STEWARD / "kept-from-tasks/phoenix-catalogue/experiments/2026-10-28-phoenix-catalogue"
    "/data/catalogue.json"
)

FAULT_WORDS = ("fault", "caused", "blame", "dive", "careless")
KEYS = {
    "id",
    "kind",
    "rule",
    "clause",
    "verdict",
    "missing_fact",
    "window",
    "candidates",
    "offender",
    "victim",
    "facts",
    "frames",
    "model_read",
    "evidence",
}


def canonical(rulings: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rulings).encode("utf-8")


def frame(te: int, incs: dict[str, int], session: str = "RACE") -> dict[str, Any]:
    """One frame on Thruxton: each car at a fixed fraction, its counter as given (-1 hides it)."""
    nums = sorted(incs, key=numkey)
    return {
        "timeElapsed": te,
        "session": session,
        "track": "Thruxton Circuit",
        "leaderLap": 1,
        "positions": [{"num": n, "pct": 0.1 * (i + 1), "pit": False} for i, n in enumerate(nums)],
        "rows": [{"num": n, "inc": incs[n], "lap": 1} for n in nums],
    }


@pytest.fixture
def make_feed(
    tmp_path: Path, feed_writer: Callable[[list[dict], Path], Path]
) -> Callable[[list[dict]], Feed]:
    def build(frames: list[dict]) -> Feed:
        return Feed.load(feed_writer(frames, tmp_path / "replay-hand.ndjson.gz"), "RACE")

    return build


def check_text(ruling: dict[str, Any]) -> None:
    assert 40 <= len(ruling["evidence"]) <= 600
    for text in [*ruling["facts"], ruling["evidence"]]:
        low = text.lower()
        for word in FAULT_WORDS:
            assert not re.search(rf"\b{word}", low), word
        assert_clean(text, names=[])


# ---------------------------------------------------------------- unit


def test_over_limit_breaches_at_limit_does_not(make_feed: Callable[[list[dict]], Feed]) -> None:
    feed = make_feed([frame(10, {"7": 0, "12": 0, "3": 0}), frame(20, {"7": 26, "12": 25, "3": 4})])
    out = incident_limit(feed, 25, "S21", "9.2.2", "999/RACE")
    assert [r["offender"] for r in out] == ["7"]
    r = out[0]
    assert set(r) == KEYS
    assert r["id"] == "999/RACE/7"
    assert r["kind"] == "incident_limit"
    assert r["rule"] == "S21" and r["clause"] == "9.2.2"
    assert r["verdict"] == "breach" and r["missing_fact"] is None
    assert r["window"] == {"session": "999/RACE"}
    assert r["candidates"] == ["7"] and r["victim"] is None
    assert r["frames"] == [] and r["model_read"] is None
    assert len(r["facts"]) == 1
    for needle in ("26", "25", "9.2.2"):
        assert needle in r["evidence"]
    assert "26" in r["facts"][0] and "25" in r["facts"][0]
    check_text(r)


def test_last_shown_counter_is_the_read(make_feed: Callable[[list[dict]], Feed]) -> None:
    # Counter hidden (-1) in the last frame: the last shown value (21) still counts.
    feed = make_feed(
        [frame(10, {"1": 5, "2": 0}), frame(20, {"1": 21, "2": 3}), frame(30, {"1": -1, "2": 3})]
    )
    out = incident_limit(feed, 20, "S21", "9.2.1", "1/HEAT 1")
    assert [r["offender"] for r in out] == ["1"]
    assert "21" in out[0]["evidence"]


def test_sorted_by_numkey(make_feed: Callable[[list[dict]], Feed]) -> None:
    feed = make_feed([frame(10, {"418": 30, "5": 30, "26": 30, "01": 30, "9": 1})])
    out = incident_limit(feed, 20, "S21", "9.2.1", "1/FEATURE")
    assert [r["offender"] for r in out] == sorted(["418", "5", "26", "01"], key=numkey)


def test_no_breach_is_empty(make_feed: Callable[[list[dict]], Feed]) -> None:
    feed = make_feed([frame(10, {"1": 20, "2": 0})])
    assert incident_limit(feed, 20, "S21", "9.2.1", "1/HEAT 1") == []


def test_one_car_without_counter_refuses(make_feed: Callable[[list[dict]], Feed]) -> None:
    feed = make_feed([frame(10, {"1": 40, "2": -1}), frame(20, {"1": 41, "2": -1})])
    out = incident_limit(feed, 20, "S21", "9.2.1", "1/HEAT 1")
    assert len(out) == 1
    r = out[0]
    assert set(r) == KEYS
    assert r["verdict"] == "unable_to_rule"
    assert r["offender"] is None and r["candidates"] == []
    assert r["missing_fact"] == MISSING_COUNTER == "incident counter not shown for every car"
    assert r["id"] == "1/HEAT 1"
    assert "9.2.1" in r["evidence"]
    check_text(r)


def test_synthetic_fixture_refuses_car_5_has_no_counter(small_feed: Feed) -> None:
    out = incident_limit(small_feed, 25, "S21", "9.2.2", "1/RACE")
    assert [r["verdict"] for r in out] == ["unable_to_rule"]
    check_text(out[0])


def test_synthetic_fixture_without_car_5(
    small_feed_frames: list[dict], make_feed: Callable[[list[dict]], Feed]
) -> None:
    for f in small_feed_frames:
        for where in ("positions", "rows"):
            f[where] = [x for x in f.get(where) or [] if str(x["num"]) != "5"]
    feed = make_feed(small_feed_frames)
    # Cars 2 and 3 end on 4, car 4 on 3: a limit of 3 catches 2 and 3 only.
    out = incident_limit(feed, 3, "S21", "9.2.2", "1/RACE")
    assert [r["offender"] for r in out] == ["2", "3"]
    for r in out:
        check_text(r)
    assert incident_limit(feed, 25, "S21", "9.2.2", "1/RACE") == []


def test_league_runs_each_session_in_order(
    tmp_path: Path, feed_writer: Callable[[list[dict], Path], Path]
) -> None:
    path = feed_writer(
        [frame(10, {"1": 30, "2": 0}, "HEAT 1"), frame(10, {"1": 30, "2": -1}, "FEATURE")],
        tmp_path / "replay-two.ndjson.gz",
    )
    league: dict[str, Any] = {
        "pack": {"path": "x", "rule_id": "S21"},
        "sessions": {
            "77/HEAT 1": {
                "feed": str(path),
                "session": "HEAT 1",
                "subsession": "77",
                "incident_limit": 20,
                "clause": "9.2.1",
            },
            "77/FEATURE": {
                "feed": str(path),
                "session": "FEATURE",
                "subsession": "77",
                "incident_limit": 20,
                "clause": "9.2.1",
            },
        },
    }
    lj = tmp_path / "league.json"
    lj.write_text(json.dumps(league), encoding="utf-8")
    out = limits_for_league(lj)
    assert [(r["id"], r["verdict"]) for r in out] == [
        ("77/HEAT 1/1", "breach"),
        ("77/FEATURE", "unable_to_rule"),
    ]
    del league["sessions"]["77/FEATURE"]["clause"]
    lj.write_text(json.dumps(league), encoding="utf-8")
    with pytest.raises(LimitsError, match="clause"):
        limits_for_league(lj)


def test_league_unreadable(tmp_path: Path) -> None:
    with pytest.raises(LimitsError, match="cannot be read"):
        limits_for_league(tmp_path / "missing.json")


# ---------------------------------------------------------------- private score


def _literal(source: str, name: str) -> Any:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in judge.py")


def _judge_rule_a(decisions: dict[str, Any], session_keys: list[str]) -> dict[str, Any]:
    """judge.py's rule A, re-run read-only: its LIMIT and A_TRUTH read from its source."""
    source = JUDGE.read_text(encoding="utf-8")
    limit_table: dict[str, int] = _literal(source, "LIMIT")
    a_truth: list[str] = _literal(source, "A_TRUTH")
    spec = importlib.util.spec_from_file_location("_rule_a_catalogue", CATALOGUE_PY)
    assert spec is not None and spec.loader is not None
    cat = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(cat)
    finally:
        sys.dont_write_bytecode = old
    breaches: dict[str, dict[str, int]] = {}
    skipped: list[str] = []
    for key in session_keys:
        sub, session = key.split("/")
        fd = cat.Feed(sub, session)
        finals = {n: max(v.values()) for n, v in fd.inc.items() if v}
        if len(finals) < len(fd.cars()):
            skipped.append(key)
            continue
        lim = limit_table[session]
        breaches[key] = {n: v for n, v in finals.items() if v > lim}
    found = 0
    ruled: dict[str, set[str]] = defaultdict(set)
    for i in a_truth:
        ok = True
        for chk in decisions[i]["incident_checks"]:
            b = breaches.get(chk["session"])
            cars = sorted(n for n, v in (b or {}).items() if v == chk["incidents"])
            ruled[chk["session"]].update(cars)
            ok = ok and bool(cars)
        found += ok
    return {
        "limit": limit_table,
        "a_truth": a_truth,
        "skipped": skipped,
        "breaches": breaches,
        "found": found,
        "unruled": {(k, n) for k, b in breaches.items() for n in b if n not in ruled[k]},
    }


def _log_unruled_counts() -> dict[str, int]:
    """The LOG's line "N breaching cars have no decision: Spa 2, ..., all 12 in Season 2"."""
    text = JUDGE_LOG.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "breaching cars have no decision" in ln)
    total = int(re.search(r"(\d+) breaching cars have no decision", line).group(1))  # type: ignore[union-attr]
    return {
        "total": total,
        "spa": int(re.search(r"Spa (\d+)", line).group(1)),  # type: ignore[union-attr]
        "snetterton_heat": int(re.search(r"Snetterton HEAT 1 (\d+)", line).group(1)),  # type: ignore[union-attr]
        "donington": int(re.search(r"Donington (\d+)", line).group(1)),  # type: ignore[union-attr]
        "season2": int(re.search(r"all (\d+) in Season 2", line).group(1)),  # type: ignore[union-attr]
    }


def _log_table() -> dict[str, list[tuple[int, list[str]]]]:
    """Rule A's table in the LOG: decision -> [(stated total, cars on it)] per session part."""
    text = JUDGE_LOG.read_text(encoding="utf-8")
    out: dict[str, list[tuple[int, list[str]]]] = {}
    for ln in text.splitlines():
        m = re.match(r"\| (\d+) \| [^|]+ \| ([\d and]+) \| \d+ \| ([^|]+) \|", ln)
        if not m:
            continue
        totals = [int(t) for t in re.findall(r"\d+", m.group(2))]
        cells = re.sub(r"\(.*?\)", "", m.group(3)).split(", then ")
        parts = [re.findall(r"\d+", c) for c in cells]
        out[m.group(1)] = list(zip(totals, parts, strict=True))
    return out


@pytest.mark.private
def test_private_rule_a_reproduced(capsys: pytest.CaptureFixture[str]) -> None:
    if not LEAGUE.exists():
        pytest.skip("data/racing/league.json is absent")
    for need in (JUDGE, JUDGE_LOG, CATALOGUE_PY, CATALOGUE_JSON):
        if not need.exists():
            pytest.skip("rule A source is absent")

    first = limits_for_league(LEAGUE)
    second = limits_for_league(LEAGUE)
    assert canonical(first) == canonical(second)

    league = json.loads(LEAGUE.read_text(encoding="utf-8"))
    session_keys = list(league["sessions"])
    decisions = {d["id"]: d for d in json.loads(CATALOGUE_JSON.read_text("utf-8"))["decisions"]}

    mine: dict[str, dict[str, int]] = defaultdict(dict)
    refused = []
    for r in first:
        if r["verdict"] == "unable_to_rule":
            refused.append(r["window"]["session"])
            continue
        session = r["window"]["session"]
        mine[session][r["offender"]] = int(re.search(r"on (\d+) incident", r["evidence"]).group(1))  # type: ignore[union-attr]
        assert r["evidence"].count(r["clause"]) == 1

    judge = _judge_rule_a(decisions, session_keys)
    # The limit and clause per session come from league.json; they must match rule A's table.
    for entry in league["sessions"].values():
        assert entry["incident_limit"] == judge["limit"][entry["session"]]
        assert entry["clause"] == ("9.2.2" if entry["session"] == "RACE" else "9.2.1")
    assert refused == judge["skipped"] == ["87937751/HEAT 1"]
    assert {k: v for k, v in mine.items()} == {k: v for k, v in judge["breaches"].items() if v}

    # 7 of 7: each decision's stated total is a breaching car's total in its session, both parts.
    a_truth = judge["a_truth"]
    assert a_truth == ["19", "20", "22", "25", "26", "27", "28"]
    table = _log_table()
    assert sorted(table, key=int) == a_truth
    found = 0
    ruled: set[tuple[str, str]] = set()
    for i in a_truth:
        checks = decisions[i]["incident_checks"]
        assert len(checks) == len(table[i])
        ok = True
        for chk, (stated, log_cars) in zip(checks, table[i], strict=True):
            assert chk["incidents"] == stated
            cars = sorted(
                (n for n, v in mine.get(chk["session"], {}).items() if v == stated), key=numkey
            )
            assert cars == sorted(log_cars, key=numkey)
            ruled.update((chk["session"], n) for n in cars)
            ok = ok and bool(cars)
        found += ok
    assert found == judge["found"] == 7

    unruled = {(k, n) for k, cars in mine.items() for n in cars if (k, n) not in ruled}
    assert unruled == judge["unruled"]
    log = _log_unruled_counts()
    assert len(unruled) == log["total"] == 21
    track = {k: e["track_short"] for k, e in league["sessions"].items()}
    by: dict[str, int] = defaultdict(int)
    for k, _n in unruled:
        by[track[k]] += 1
        if k.endswith("/HEAT 1") and track[k] == "Snetterton":
            by["SnetH"] += 1
    assert by["Spa"] == log["spa"]
    assert by["SnetH"] == log["snetterton_heat"]
    assert by["Donington"] == log["donington"]
    assert by["Cadwell"] + by["Thruxton"] == log["season2"]

    with capsys.disabled():
        print(
            f"\nrule A: {found}/7 found, {sum(len(v) for v in mine.values())} breaches, "
            f"{len(unruled)} with no decision, {len(refused)} session refused"
        )
