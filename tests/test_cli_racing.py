"""Tests for the `faultline` command line: racing limits, racing judge (locate) and replay.

Everything runs on synthetic data: the small feed of `tests/adapters/conftest.py` (made-up
cars "1" to "6", invented names "Test Driver A" to "F"), a league and six protests from
`tests/fixtures/racing/cli/`, and a one-rule pack, all written into `tmp_path` at test time.
"""

from __future__ import annotations

import ast
import dataclasses
import gzip
import hashlib
import json
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx
import pytest
from adapters.conftest import write_feed
from test_public_tree import CORE_WORDS, _imports_adapter

from faultline import cli, client, record
from faultline.adapters.pitbot import cli as racing_cli
from faultline.adapters.pitbot.feed import Feed
from faultline.adapters.pitbot.locator import NO_CAR, NO_EVENT_LAP, Window

REPO = Path(__file__).resolve().parent.parent
CLI_FIXTURES = REPO / "tests" / "fixtures" / "racing" / "cli"
SMALL_FEED_JSON = REPO / "tests" / "fixtures" / "racing" / "feed_small.json"
PLANTED_NAMES = {
    "1": "Alder Quimbley",
    "2": "Bryony Fenwhistle",
    "3": "Odile Vantongeren",
    "4": "Casimir Holloway",
    "5": "Delphine Marrowby",
    "6": "Evander Tolliver",
}
PLANTED = tuple(token.casefold() for name in PLANTED_NAMES.values() for token in name.split()) + (
    "quentin",
    "ravelstone",
)


# ---------------------------------------------------------------- the synthetic world


def _frames() -> list[dict[str, Any]]:
    """The small feed with planted invented names the output must never carry.

    The fixture's own names all hold "Driver", which the normaliser's own placeholder
    "[unresolved driver]" also holds, so its leak lint would refuse any masked name here.
    """
    frames = json.loads(SMALL_FEED_JSON.read_text(encoding="utf-8"))
    for frame in frames:
        for item in (frame.get("positions") or []) + (frame.get("rows") or []):
            if item.get("num") in PLANTED_NAMES:
                item["name"] = PLANTED_NAMES[item["num"]]
    return frames


def _all_counters_shown(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The small feed with car 5's counter shown as 0 in every row."""
    for frame in frames:
        for row in frame.get("rows") or []:
            if row.get("num") == "5":
                row["inc"] = 0
    return frames


def _write_reports(path: Path, reports: list[dict[str, Any]]) -> Path:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in reports), encoding="utf-8"
    )
    return path


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """Feeds, league.json, reports.jsonl and a rules pack, all in `tmp_path/in`."""
    base = tmp_path / "in"
    base.mkdir()
    feed_a = write_feed(_frames(), base / "replay-a.ndjson.gz")
    feed_b = write_feed(_all_counters_shown(_frames()), base / "replay-b.ndjson.gz")
    league = json.loads((CLI_FIXTURES / "league.json").read_text(encoding="utf-8"))
    league["sessions"]["9000100/RACE"].update(feed=str(feed_a), stream=str(base / "a.video"))
    league["sessions"]["9000200/RACE"].update(feed=str(feed_b), stream=str(base / "b.video"))
    league_path = base / "league.json"
    league_path.write_text(json.dumps(league, indent=2), encoding="utf-8")
    reports = json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))
    reports_path = _write_reports(base / "reports.jsonl", reports)
    pack = base / "pack"
    pack.mkdir()
    (pack / "pack.json").write_text(
        json.dumps({"name": "Test Pack", "version": "1", "domain": "racing"}), encoding="utf-8"
    )
    (pack / "t1.md").write_text(
        "---\nid: T1\ntitle: Contact\n---\nDrivers must leave room.\n", encoding="utf-8"
    )
    return {"base": base, "league": league_path, "reports": reports_path, "pack": pack}


def run(*argv: str | Path) -> int:
    return cli.main([str(a) for a in argv])


def judge(world: dict[str, Path], out: Path, *extra: str | Path, stage: str = "locate") -> int:
    return run(
        "racing",
        "judge",
        world["reports"],
        *extra,
        "--league",
        world["league"],
        "--rules",
        world["pack"],
        "--out",
        out,
        "--stage",
        stage,
    )


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def by_id(path: Path) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in lines(path)}


# ---------------------------------------------------------------- limits


def test_limits_twice_gives_identical_bytes(world: dict[str, Path], tmp_path: Path) -> None:
    one, two = tmp_path / "o1" / "limits.jsonl", tmp_path / "o2" / "limits.jsonl"
    assert run("racing", "limits", "--league", world["league"], "--out", one) == 0
    assert run("racing", "limits", "--league", world["league"], "--out", two) == 0
    assert one.read_bytes() == two.read_bytes()
    rows = lines(one)
    # Session 9000100 hides car 5's counter: one refusal. Session 9000200 shows every
    # counter and its limit is 2: cars 2 and 3 (4 points) and car 4 (3 points) breach.
    assert [(r["id"], r["verdict"]) for r in rows] == [
        ("9000100/RACE", "unable_to_rule"),
        ("9000200/RACE/2", "breach"),
        ("9000200/RACE/3", "breach"),
        ("9000200/RACE/4", "breach"),
    ]
    for row in rows:
        assert row["kind"] == "incident_limit"
        assert row["rule"] == "T1"
        bundle = record.read_bundle(one, row["record"])
        assert record.record_hash(bundle) == row["record"]
        assert bundle["ruling"] == {k: v for k, v in row.items() if k != "record"}


def test_limits_lines_end_in_newline_and_are_canonical(
    world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "limits.jsonl"
    assert run("racing", "limits", "--league", world["league"], "--out", out) == 0
    raw = out.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    for line in raw.splitlines():
        assert record.canonical(json.loads(line)) == line


# ---------------------------------------------------------------- judge, locate stage


def test_locate_twice_gives_identical_bytes(world: dict[str, Path], tmp_path: Path) -> None:
    one, two = tmp_path / "o1" / "locate.jsonl", tmp_path / "o2" / "locate.jsonl"
    assert judge(world, one) == 0
    assert judge(world, two) == 0
    assert one.read_bytes() == two.read_bytes()


def test_locate_lines_follow_the_contract(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    rows = lines(out)
    assert [r["id"] for r in rows] == ["1", "2", "3", "4", "5", "10"]
    keys = {
        "id", "kind", "rule", "clause", "verdict", "missing_fact", "window", "candidates",
        "offender", "victim", "facts", "frames", "model_read", "evidence", "record",
    }  # fmt: skip
    for row in rows:
        assert set(row) == keys
        assert row["kind"] == "contact"
        assert row["rule"] == "T1"
        assert row["clause"] is None
        assert row["offender"] is None and row["victim"] is None
        assert row["frames"] == [] and row["model_read"] is None
        assert row["verdict"] in ("steward_review", "unable_to_rule")
        assert (row["verdict"] == "unable_to_rule") == (row["missing_fact"] is not None)
        assert 40 <= len(row["evidence"]) <= 600
        assert len(row["record"]) == 64

    one = by_id(out)["1"]
    assert one["verdict"] == "steward_review"
    w = one["window"]
    assert set(w) == {"session", "te", "lap", "stream_s", "offset_error_s"}
    assert w["session"] == "9000100/RACE"
    assert w["te"] == [103, 109]
    assert w["lap"] == 4
    assert w["stream_s"] == [1103.0, 1109.0]
    assert w["offset_error_s"] == 2.0
    assert {"2", "3"} <= set(one["candidates"])
    assert one["candidates"] == sorted(one["candidates"], key=int)
    assert one["facts"] and all(isinstance(f, str) for f in one["facts"])
    assert "car 2" in one["evidence"] and "car 3" in one["evidence"]


def test_locator_refusals_keep_the_session(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    five = by_id(out)["5"]
    assert five["verdict"] == "unable_to_rule"
    assert five["missing_fact"] == NO_EVENT_LAP
    assert five["window"] == {"session": "9000100/RACE"}
    assert five["candidates"] == [] and five["facts"] == []


def test_no_feed_and_no_session_refuse(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    rows = by_id(out)
    assert rows["2"]["missing_fact"] == racing_cli.NO_SESSION
    assert rows["2"]["window"] == {"session": None}
    assert rows["3"]["missing_fact"] == racing_cli.NO_FEED
    assert rows["3"]["window"] == {"session": "9000999/RACE"}
    for rid in ("2", "3"):
        assert rows[rid]["verdict"] == "unable_to_rule"
        assert rows[rid]["candidates"] == []


def test_a_session_entry_without_a_feed_refuses(world: dict[str, Path], tmp_path: Path) -> None:
    league = json.loads(world["league"].read_text(encoding="utf-8"))
    del league["sessions"]["9000100/RACE"]["feed"]
    world["league"].write_text(json.dumps(league), encoding="utf-8")
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    one = by_id(out)["1"]
    assert one["missing_fact"] == racing_cli.NO_FEED
    assert one["window"] == {"session": "9000100/RACE"}


def test_a_report_naming_no_car_refuses(world: dict[str, Path], tmp_path: Path) -> None:
    reports = [
        {**json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))[0]},
    ]
    reports[0].update(id="7", reporter_car="", description="Someone hit someone on lap 4.")
    path = _write_reports(world["base"] / "nocar.jsonl", reports)
    out = tmp_path / "locate.jsonl"
    assert (
        run("racing", "judge", path, "--league", world["league"], "--rules", world["pack"],
            "--out", out, "--stage", "locate")
        == 0
    )  # fmt: skip
    assert by_id(out)["7"]["missing_fact"] == NO_CAR


def test_several_report_files_are_read_and_sorted(world: dict[str, Path], tmp_path: Path) -> None:
    reports = json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))
    first = _write_reports(world["base"] / "first.jsonl", reports[3:])
    world["reports"] = _write_reports(world["base"] / "second.jsonl", reports[:3])
    out = tmp_path / "locate.jsonl"
    assert judge(world, out, first) == 0
    assert [r["id"] for r in lines(out)] == ["1", "2", "3", "4", "5", "10"]


def test_a_duplicate_report_id_is_refused(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out, world["reports"]) == 2
    assert "more than once" in capsys.readouterr().err
    assert not out.exists()


def test_a_rule_missing_from_the_pack_is_refused(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    league = json.loads(world["league"].read_text(encoding="utf-8"))
    league["pack"]["rule_id"] = "T9"
    world["league"].write_text(json.dumps(league), encoding="utf-8")
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 2
    assert "no rule 'T9'" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("stage", ["frames", "rule"])
def test_later_stages_need_masks(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str], stage: str
) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out, stage=stage) != 0
    err = capsys.readouterr().err.strip()
    assert "needs --masks" in err and stage in err
    assert len(err.splitlines()) == 1
    assert not out.exists()


def test_the_rule_stage_needs_a_model(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "rule.jsonl"
    assert judge(world, out, "--masks", CLI_FIXTURES / "masks.json", stage="rule") == 2
    assert "needs --model" in capsys.readouterr().err
    assert not out.exists()


def test_an_unknown_stage_is_refused_by_the_parser(world: dict[str, Path], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        judge(world, tmp_path / "x.jsonl", stage="nonsense")
    assert exc.value.code != 0


def test_an_event_car_far_from_every_protest_car_is_not_a_candidate(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Focus is the protest cars only: an event car never within 8 m of one is left out."""
    real_locate = racing_cli.locate

    def locate_with_far_car(*args: Any, **kwargs: Any) -> Any:
        found = real_locate(*args, **kwargs)
        if isinstance(found, Window):
            found = dataclasses.replace(found, event_cars=(*found.event_cars, "6"))
        return found

    monkeypatch.setattr(racing_cli, "locate", locate_with_far_car)
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    one = by_id(out)["1"]
    assert one["verdict"] == "steward_review"
    bundle = record.read_bundle(out, one["record"])
    assert "6" in bundle["detail"]["locate"]["event_cars"]
    assert bundle["detail"]["locate"]["focus"] == ["2", "3"]
    # Car 6 is more than 8 m from cars 2 and 3 at every second of the padded window.
    feed = Feed.load(world["base"] / "replay-a.ndjson.gz", "RACE")
    lo, hi = one["window"]["te"]
    gaps = [
        abs(g)
        for te in range(lo - racing_cli.PAD_S, hi + racing_cli.PAD_S + 1)
        for other in ("2", "3")
        if (g := feed.gap_m("6", other, te)) is not None
    ]
    assert gaps and min(gaps) > racing_cli.NEAR_M
    assert "6" not in one["candidates"]
    assert "car 6" not in " ".join(one["facts"])


def test_focus_is_the_protest_cars_not_the_event_cars(
    world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    ten = by_id(out)["10"]
    assert ten["verdict"] == "steward_review"
    detail = record.read_bundle(out, ten["record"])["detail"]["locate"]
    assert detail["focus"] == ["4"]


def test_an_empty_closed_set_refuses_with_the_session_only(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """Car 7 is only ever in rows[]: its +2 rise gives a window, but it has no position."""
    frames = _frames()
    for frame in frames:
        inc = 2 if frame["timeElapsed"] >= 130 else 0
        frame.setdefault("rows", []).append(
            {"inc": inc, "lap": 4, "name": "Fenella Rowanbright", "num": "7"}
        )
    write_feed(frames, world["base"] / "replay-a.ndjson.gz")
    reports = json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))
    reports = [{**reports[0], "id": "8", "reporter_car": "", "description": "Car 7 on lap 4."}]
    path = _write_reports(world["base"] / "empty.jsonl", reports)
    out = tmp_path / "locate.jsonl"
    assert (
        run("racing", "judge", path, "--league", world["league"], "--rules", world["pack"],
            "--out", out, "--stage", "locate")
        == 0
    )  # fmt: skip
    eight = by_id(out)["8"]
    assert eight["verdict"] == "unable_to_rule"
    assert eight["missing_fact"] == racing_cli.EMPTY_SET
    assert eight["window"] == {"session": "9000100/RACE"}
    assert eight["candidates"] == [] and eight["facts"] == []
    assert "could not be placed" not in eight["evidence"]
    assert "closed set is empty" in eight["evidence"]
    detail = record.read_bundle(out, eight["record"])["detail"]["locate"]
    assert detail["focus"] == ["7"] and detail["event_cars"] == ["7"]
    assert detail["window"]["te"][0] <= 130 <= detail["window"]["te"][1]
    assert "fenella" not in _written_text(out) and "rowanbright" not in _written_text(out)
    replayed = tmp_path / "replayed.jsonl"
    assert run("replay", out, "--out", replayed) == 0
    assert replayed.read_bytes() == out.read_bytes()


def test_a_name_in_an_unresolved_reporter_car_stops_the_write(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))
    reports = [{**reports[0], "id": "9", "reporter_car": "Vantongeren"}]
    path = _write_reports(world["base"] / "named.jsonl", reports)
    out = tmp_path / "locate.jsonl"
    assert (
        run("racing", "judge", path, "--league", world["league"], "--rules", world["pack"],
            "--out", out, "--stage", "locate")
        == 2
    )  # fmt: skip
    err = capsys.readouterr().err
    assert "ruling 9" in err and "leak lint" in err
    assert "vantongeren" not in err.casefold()
    assert not out.exists() and not record.bundle_dir(out).exists()


def test_a_session_entry_without_a_feed_has_no_feed_hash(world: dict[str, Path]) -> None:
    league = json.loads(world["league"].read_text(encoding="utf-8"))
    del league["sessions"]["9000100/RACE"]["feed"]
    world["league"].write_text(json.dumps(league), encoding="utf-8")
    loaded = racing_cli._League(world["league"])
    with pytest.raises(racing_cli.RacingCliError, match="has no feed"):
        loaded.feed_sha("9000100/RACE")
    with pytest.raises(racing_cli.RacingCliError, match="has no feed"):
        loaded.feed_sha("9000999/RACE")


def test_limits_on_a_session_without_a_feed_exits_cleanly(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    league = json.loads(world["league"].read_text(encoding="utf-8"))
    del league["sessions"]["9000200/RACE"]["feed"]
    world["league"].write_text(json.dumps(league), encoding="utf-8")
    out = tmp_path / "limits.jsonl"
    assert run("racing", "limits", "--league", world["league"], "--out", out) == 2
    err = capsys.readouterr().err
    assert err.startswith("faultline: ") and "Traceback" not in err
    assert not out.exists()


# ---------------------------------------------------------------- names never leave


def _written_text(out: Path) -> str:
    texts = [out.read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in sorted(record.bundle_dir(out).iterdir())]
    return "\n".join(texts).casefold()


def test_a_planted_name_never_reaches_the_output(world: dict[str, Path], tmp_path: Path) -> None:
    names = world["base"] / "names.txt"
    names.write_text("Quentin Ravelstone\n", encoding="utf-8")
    out = tmp_path / "locate.jsonl"
    assert judge(world, out, "--known-names", names) == 0
    four = by_id(out)["4"]
    assert four["verdict"] == "steward_review"
    written = _written_text(out)
    for planted in PLANTED:
        assert planted not in written, planted
    bundle = record.read_bundle(out, four["record"])
    assert "[unresolved driver]" in bundle["detail"]["locate"]["normalised"]["text"]
    assert "car 3" in bundle["detail"]["locate"]["normalised"]["text"]


def test_a_name_in_limits_output_is_impossible(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "limits.jsonl"
    assert run("racing", "limits", "--league", world["league"], "--out", out) == 0
    written = _written_text(out)
    for planted in PLANTED:
        assert planted not in written, planted


def test_a_text_failing_the_lint_stops_the_write(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leaky(*_args: Any, **_kwargs: Any) -> list[str]:
        return ["Bryony Fenwhistle was close behind."]

    monkeypatch.setattr(racing_cli, "facts", leaky)
    out = tmp_path / "locate.jsonl"
    with pytest.raises(racing_cli.RacingCliError, match="leak lint"):
        racing_cli.judge([world["reports"]], world["league"], world["pack"], out, "locate")
    assert not out.exists()


# ---------------------------------------------------------------- records and replay


def test_records_hash_content_not_paths(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "o1" / "locate.jsonl"
    assert judge(world, out) == 0
    # The same inputs moved to another folder give the same bytes.
    moved = tmp_path / "moved"
    shutil.copytree(world["base"], moved)
    league = json.loads((moved / "league.json").read_text(encoding="utf-8"))
    for key, name in (("9000100/RACE", "replay-a"), ("9000200/RACE", "replay-b")):
        league["sessions"][key]["feed"] = str(moved / f"{name}.ndjson.gz")
    (moved / "league.json").write_text(json.dumps(league), encoding="utf-8")
    other = tmp_path / "o2" / "locate.jsonl"
    assert (
        run("racing", "judge", moved / "reports.jsonl", "--league", moved / "league.json",
            "--rules", moved / "pack", "--out", other, "--stage", "locate")
        == 0
    )  # fmt: skip
    assert out.read_bytes() == other.read_bytes()
    for bundle in record.bundle_dir(out).iterdir():
        text = bundle.read_text(encoding="utf-8")
        assert str(tmp_path).casefold() not in text.casefold()
        assert "replay-a" not in text and ".video" not in text


def test_a_changed_feed_changes_the_record(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "o1" / "locate.jsonl"
    assert judge(world, out) == 0
    frames = _frames()
    frames[-1]["leaderLap"] = 99
    write_feed(frames, world["base"] / "replay-a.ndjson.gz")
    other = tmp_path / "o2" / "locate.jsonl"
    assert judge(world, other) == 0
    assert by_id(out)["1"]["record"] != by_id(other)["1"]["record"]
    assert by_id(out)["2"]["record"] == by_id(other)["2"]["record"]  # no feed read for it


@pytest.mark.parametrize("command", ["limits", "judge"])
def test_replay_is_byte_identical(world: dict[str, Path], tmp_path: Path, command: str) -> None:
    preds = tmp_path / "preds.jsonl"
    if command == "limits":
        assert run("racing", "limits", "--league", world["league"], "--out", preds) == 0
    else:
        assert judge(world, preds) == 0
    again = tmp_path / "replayed" / "preds2.jsonl"
    assert run("replay", preds, "--out", again) == 0
    assert again.read_bytes() == preds.read_bytes()
    # The replayed file carries its own bundles, so it replays again.
    third = tmp_path / "preds3.jsonl"
    assert run("replay", again, "--out", third) == 0
    assert third.read_bytes() == preds.read_bytes()


def test_replay_reads_no_source(world: dict[str, Path], tmp_path: Path) -> None:
    preds = tmp_path / "preds.jsonl"
    assert judge(world, preds) == 0
    shutil.rmtree(world["base"])
    again = tmp_path / "preds2.jsonl"
    assert run("replay", preds, "--out", again) == 0
    assert again.read_bytes() == preds.read_bytes()


def _tamper_bundle(preds: Path, rid: str) -> None:
    row = by_id(preds)[rid]
    path = record.bundle_dir(preds) / f"{row['record']}.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["ruling"]["verdict"] = "breach"
    path.write_bytes(record.canonical(bundle) + b"\n")


def test_a_tampered_bundle_refuses(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preds = tmp_path / "preds.jsonl"
    assert judge(world, preds) == 0
    _tamper_bundle(preds, "4")
    again = tmp_path / "preds2.jsonl"
    assert run("replay", preds, "--out", again) == 2
    err = capsys.readouterr().err
    assert "line '4'" in err and "does not hash to its record" in err
    assert not again.exists()


def test_a_tampered_input_hash_refuses(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preds = tmp_path / "preds.jsonl"
    assert run("racing", "limits", "--league", world["league"], "--out", preds) == 0
    row = lines(preds)[1]
    path = record.bundle_dir(preds) / f"{row['record']}.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["inputs"]["feed_sha256"] = "0" * 64
    path.write_bytes(record.canonical(bundle) + b"\n")
    assert run("replay", preds, "--out", tmp_path / "preds2.jsonl") == 2
    assert f"line {row['id']!r}" in capsys.readouterr().err


def test_a_tampered_line_refuses(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preds = tmp_path / "preds.jsonl"
    assert judge(world, preds) == 0
    rows = lines(preds)
    rows[0]["verdict"] = "breach"
    preds.write_bytes(b"".join(record.canonical(r) + b"\n" for r in rows))
    assert run("replay", preds, "--out", tmp_path / "preds2.jsonl") == 2
    assert "line '1'" in capsys.readouterr().err


def test_a_missing_bundle_refuses(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    preds = tmp_path / "preds.jsonl"
    assert judge(world, preds) == 0
    row = by_id(preds)["10"]
    (record.bundle_dir(preds) / f"{row['record']}.json").unlink()
    assert run("replay", preds, "--out", tmp_path / "preds2.jsonl") == 2
    assert "line '10'" in capsys.readouterr().err


def test_a_verifier_runs_on_its_input_key(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preds = tmp_path / "preds.jsonl"
    assert judge(world, preds) == 0
    seen: list[Any] = []
    monkeypatch.setitem(cli.VERIFIERS, "rule", lambda _p, value: seen.append(value["id"]))
    assert run("replay", preds, "--out", tmp_path / "preds2.jsonl") == 0
    assert seen == ["T1"] * 6


# ---------------------------------------------------------------- the steward gives the moment


def _moments() -> dict[str, dict[str, Any]]:
    return json.loads((CLI_FIXTURES / "moments.json").read_text(encoding="utf-8"))["moments"]


def test_without_moments_locate_is_byte_identical_to_before(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """The hashes of a locate run taken before the moments, masks, frames and rule options."""
    before = json.loads((CLI_FIXTURES / "locate_before.json").read_text(encoding="utf-8"))
    out = tmp_path / "locate.jsonl"
    assert judge(world, out) == 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before["preds_sha256"]
    bundles = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(record.bundle_dir(out).iterdir())
    }
    assert bundles == before["bundles"]


def test_a_moment_builds_the_window_around_it(world: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out, "--moments", CLI_FIXTURES / "moments.json") == 0
    rows = by_id(out)
    moments = _moments()
    feed = Feed.load(world["base"] / "replay-a.ndjson.gz", "RACE")

    one = rows["1"]
    m = moments["1"]["te"]
    assert one["verdict"] == "steward_review"
    assert one["window"] == {
        "session": "9000100/RACE",
        "te": [m - 3, m + 2],
        "lap": feed.leader_lap(m),
        "stream_s": [m - 3 + 1000.0, m + 2 + 1000.0],
        "offset_error_s": 2.0,
    }
    bundle = record.read_bundle(out, one["record"])
    assert bundle["inputs"]["moment"] == moments["1"]
    detail = bundle["detail"]["locate"]
    assert detail["contact_te"] == m and detail["moment"] == moments["1"]
    # The locator still ran; its own window is kept for reference only.
    assert detail["locator"]["result"] == "window"
    assert detail["locator"]["te"] != one["window"]["te"]
    assert "the steward gave feed second" in one["evidence"].casefold()

    # The locator refuses report 5, but the steward's moment still places it.
    five = record.read_bundle(out, rows["5"]["record"])["detail"]["locate"]
    assert five["locator"] == {
        "result": "refusal",
        "missing_fact": NO_EVENT_LAP,
        "session": "9000100/RACE",
    }
    assert five["window"]["te"] == [moments["5"]["te"] - 3, moments["5"]["te"] + 2]

    # A report with no feed still refuses, its moment recorded beside the refusal.
    three = rows["3"]
    assert three["missing_fact"] == racing_cli.NO_FEED
    assert record.read_bundle(out, three["record"])["inputs"]["moment"] == moments["3"]

    # A report with no moment keeps the locator's window exactly.
    plain = tmp_path / "plain.jsonl"
    assert judge(world, plain) == 0
    assert rows["10"] == by_id(plain)["10"]


def test_a_bad_moments_file_is_refused(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = world["base"] / "moments.json"
    bad.write_text(json.dumps({"moments": {"1": {"te": "120", "source": "x"}}}), "utf-8")
    assert judge(world, tmp_path / "x.jsonl", "--moments", bad) == 2
    assert "te is not a whole second" in capsys.readouterr().err


# ---------------------------------------------------------------- frames and rule stages

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg and ffprobe are not on PATH")
VIDEO_S = 80
OFFSET_S = -80.0  # feed second te shows at stream second te - 80 in the test video
MODEL = "muse-spark-1.3"
REASON = "Rule T1: frame 9 shows the front of one car meeting the rear of the other."


@pytest.fixture(scope="module")
def test_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg and ffprobe are not on PATH")
    path = tmp_path_factory.mktemp("video") / "stream.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         f"testsrc=duration={VIDEO_S}:size=320x180:rate=5", "-pix_fmt", "yuv420p", str(path)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


@pytest.fixture
def video_world(world: dict[str, Path], test_video: Path) -> dict[str, Path]:
    """The world with session 9000100 on the test video, and three reports: 1, 3 and 4."""
    league = json.loads(world["league"].read_text(encoding="utf-8"))
    league["sessions"]["9000100/RACE"].update(stream=str(test_video), offset_s=OFFSET_S)
    world["league"].write_text(json.dumps(league, indent=2), encoding="utf-8")
    reports = json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))
    keep = [r for r in reports if r["id"] in ("1", "3", "4")]
    world["reports"] = _write_reports(world["base"] / "three.jsonl", keep)
    return world


def stage_run(world: dict[str, Path], out: Path, stage: str, *extra: str | Path) -> int:
    masks = ("--masks", CLI_FIXTURES / "masks.json")
    moments = ("--moments", CLI_FIXTURES / "moments.json")
    return judge(world, out, *masks, *moments, *extra, stage=stage)


def _fake_model(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The fake model on, every other key unset; counts calls that reach `client.chat`."""
    for name in ("MODEL_API_KEY", "MODEL_API_BASE", "STEWARD_ENV_FILE", "FAULTLINE_CAP_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    calls: list[int] = []
    real = client.chat

    def counting(*args: Any, **kwargs: Any) -> client.Reply:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(client, "chat", counting)
    return calls


def _no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the model client was called")

    monkeypatch.setattr(client, "chat", boom)
    monkeypatch.setattr(client, "CLIENT", boom)


def _gray(jpg: Path) -> bytes:
    done = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(jpg), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True,
        capture_output=True,
    )
    return done.stdout


def _region_max(pixels: bytes, x0: int, y0: int, x1: int, y1: int) -> int:
    return max(pixels[y * 1280 + x] for y in range(y0, y1) for x in range(x0, x1))


@needs_ffmpeg
def test_frames_stage_cuts_masked_frames_around_the_moment(
    video_world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "frames.jsonl"
    assert stage_run(video_world, out, "frames") == 0
    rows = by_id(out)
    one = rows["1"]
    m = _moments()["1"]["te"]
    assert one["verdict"] == "steward_review"
    assert len(one["frames"]) == 17
    assert [f["stream_s"] for f in one["frames"]][8] == m + OFFSET_S
    assert one["frames"][0]["stream_s"] == m + OFFSET_S - 4
    bundle = record.read_bundle(out, one["record"])
    inputs = bundle["inputs"]
    masks = json.loads((CLI_FIXTURES / "masks.json").read_text(encoding="utf-8"))
    session_masks = masks["default"] + masks["sessions"]["9000100/RACE"]
    assert inputs["masks_sha256"] == record.record_hash(session_masks)
    assert inputs["frame_sha256"] == [f["sha256"] for f in one["frames"]]
    assert inputs["ffmpeg_version"].startswith("ffmpeg version")
    frames_dir = Path(f"{out}.frames")
    for f in one["frames"]:
        data = (frames_dir / f"{f['sha256']}.jpg").read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"]
    # Both masks hold: the default's top-left box and the session's own bottom-right box.
    pixels = _gray(frames_dir / f"{one['frames'][8]['sha256']}.jpg")
    assert _region_max(pixels, 8, 8, 192, 112) < 40
    assert _region_max(pixels, 1088, 608, 1272, 712) < 40
    assert _region_max(pixels, 400, 200, 800, 500) > 100
    # The report with no feed still refuses and has no frames.
    assert rows["3"]["missing_fact"] == racing_cli.NO_FEED and rows["3"]["frames"] == []


@needs_ffmpeg
def test_drop_layouts_are_recorded_and_an_all_dropped_window_refuses(
    video_world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "frames.jsonl"
    assert stage_run(video_world, out, "frames") == 0
    one = by_id(out)["1"]
    bundle = record.read_bundle(out, one["record"])
    masks = json.loads((CLI_FIXTURES / "masks.json").read_text(encoding="utf-8"))
    assert bundle["inputs"]["drop_rules_sha256"] == record.record_hash(masks["drop_layouts"])
    assert bundle["detail"]["frames"]["dropped"] == []  # the test video has one layout only

    # A rule every pixel matches: every second is another layout, so nothing can be shown.
    everything = {"name": "any", "probes": [[640, 360]], "rgb_min": [0, 0, 0]}
    masks["drop_layouts"] = [{**everything, "rgb_max": [255, 255, 255]}]
    path = video_world["base"] / "masks-all.json"
    path.write_text(json.dumps(masks), encoding="utf-8")
    other = tmp_path / "all.jsonl"
    moments = ("--moments", CLI_FIXTURES / "moments.json")
    assert judge(video_world, other, "--masks", path, *moments, stage="frames") == 0
    refused = by_id(other)["1"]
    assert refused["verdict"] == "unable_to_rule"
    assert refused["missing_fact"] == racing_cli.NO_STANDARD_VIEW
    assert refused["frames"] == [] and refused["window"] == {"session": "9000100/RACE"}
    assert racing_cli.NO_STANDARD_VIEW in refused["evidence"]
    assert not Path(f"{other}.frames").exists() or not list(Path(f"{other}.frames").iterdir())


@needs_ffmpeg
def test_frames_stage_twice_gives_equal_bytes(video_world: dict[str, Path], tmp_path: Path) -> None:
    one, two = tmp_path / "o1" / "frames.jsonl", tmp_path / "o2" / "frames.jsonl"
    assert stage_run(video_world, one, "frames") == 0
    assert stage_run(video_world, two, "frames") == 0
    assert one.read_bytes() == two.read_bytes()


@needs_ffmpeg
def test_a_moment_near_the_stream_end_refuses_not_covered(
    video_world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "frames.jsonl"
    assert stage_run(video_world, out, "frames") == 0
    four = by_id(out)["4"]
    assert four["verdict"] == "unable_to_rule"
    assert four["missing_fact"] == "stream does not cover the window"
    assert four["window"] == {"session": "9000100/RACE"}
    assert four["frames"] == [] and four["candidates"] == []
    bundle = record.read_bundle(out, four["record"])
    assert "frame_sha256" not in bundle["inputs"]
    assert bundle["detail"]["frames"]["refused"] == "stream does not cover the window"
    assert bundle["detail"]["locate"]["window"]["te"] == [152, 157]


@needs_ffmpeg
def test_without_moments_frames_centre_on_the_contact_second(
    video_world: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "frames.jsonl"
    assert judge(video_world, out, "--masks", CLI_FIXTURES / "masks.json", stage="frames") == 0
    one = by_id(out)["1"]
    contact = record.read_bundle(out, one["record"])["detail"]["locate"]["contact_te"]
    assert one["frames"][8]["stream_s"] == round(contact + OFFSET_S, 1)
    assert "moment" not in record.read_bundle(out, one["record"])["inputs"]


@needs_ffmpeg
def test_any_other_frames_error_stops_the_run(
    video_world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    league = json.loads(video_world["league"].read_text(encoding="utf-8"))
    league["sessions"]["9000100/RACE"]["stream"] = str(video_world["base"] / "absent.mp4")
    video_world["league"].write_text(json.dumps(league), encoding="utf-8")
    out = tmp_path / "frames.jsonl"
    assert stage_run(video_world, out, "frames") == 2
    assert "stream file is missing" in capsys.readouterr().err
    assert not out.exists()


def _hide_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No ffmpeg anywhere: `shutil.which` finds nothing and PATH holds one empty folder."""
    empty = tmp_path / "no-tools"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)


@needs_ffmpeg
def test_frames_replay_is_byte_identical_and_a_changed_frame_refuses(
    video_world: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "frames.jsonl"
    assert stage_run(video_world, out, "frames") == 0
    _hide_ffmpeg(monkeypatch, tmp_path)
    again = tmp_path / "replayed.jsonl"
    assert run("replay", out, "--out", again) == 0
    assert again.read_bytes() == out.read_bytes()
    sha = by_id(out)["1"]["frames"][3]["sha256"]
    (Path(f"{out}.frames") / f"{sha}.jpg").write_bytes(b"\xff\xd8changed\xff\xd9")
    assert run("replay", out, "--out", tmp_path / "third.jsonl") == 2
    assert "has changed" in capsys.readouterr().err


@needs_ffmpeg
def test_rule_stage_under_the_fake_model_twice_and_replay(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_model(monkeypatch)
    one, two = tmp_path / "rule.jsonl", tmp_path / "rule2.jsonl"
    args = ("--model", "fake", "--arm", "2")
    assert stage_run(video_world, one, "rule", *args) == 0
    assert len(calls) == 3  # one steward_review line, three runs
    assert stage_run(video_world, two, "rule", *args) == 0
    assert len(calls) == 3  # the second run came from the ledger alone
    assert one.read_bytes() == two.read_bytes()
    assert not (tmp_path / "ledger" / racing_cli.LOCK_NAME).exists()  # released

    row = by_id(one)["1"]
    assert row["verdict"] == "steward_review"
    read = row["model_read"]
    assert read["model"] == "fake" and read["runs"] == 3 and read["source"] == "fake"
    assert set(read) == {
        "model", "runs", "agreed", "verdict", "offender", "reason", "parse_failures",
        "lint_hits", "source",
    }  # fmt: skip
    if not (read["agreed"] and read["verdict"] == "penalty"):
        assert row["offender"] is None
    inputs = record.read_bundle(one, row["record"])["inputs"]
    assert len(inputs["ledger_keys"]) == 3
    call = inputs["model_call"]
    assert call["ref"] == "1-arm2" and call["json_mode"] is True and call["source"] == "fake"
    assert call["schema_form"] == "enum"
    assert len(row["frames"]) == 17  # the line keeps every cut frame
    assert call["images"] == 8
    sent = [f for f in row["frames"] if float(f["stream_s"]).is_integer()][:8]
    assert call["frame_sha256"] == [f["sha256"] for f in sent]
    assert call["frame_labels"] == [f"frame {i}" for i in range(1, 9)]
    for rid in ("3", "4"):
        assert by_id(one)[rid]["model_read"] is None

    # Replay with the client seam raising, the fake model off and no ffmpeg on the machine.
    monkeypatch.delenv("FAULTLINE_FAKE_MODEL")
    _no_client(monkeypatch)
    _hide_ffmpeg(monkeypatch, tmp_path)
    again = tmp_path / "replayed.jsonl"
    assert run("replay", one, "--out", again) == 0
    assert again.read_bytes() == one.read_bytes()


# ---------------------------------------------------------------- frames sent to the model


def _cut_seconds(centre: float, drop: tuple[float, ...] = ()) -> list[float]:
    """The cut's seconds: 2 a second over [centre-4, centre+4], less the dropped ones."""
    every = [round(centre - 4 + i / 2, 1) for i in range(17)]
    return [s for s in every if s not in drop]


def test_pick_model_frames_sends_eight_whole_seconds_from_four_before() -> None:
    seconds = _cut_seconds(104.0)
    got = racing_cli.pick_model_frames(seconds, 104.0, 8)
    assert got == [0, 2, 4, 6, 8, 10, 12, 14]
    assert [seconds[i] for i in got] == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]


def test_pick_model_frames_with_dropped_seconds_fills_what_it_can() -> None:
    # 102.0 and its neighbour 102.5 dropped: the 102 slot takes 101.5 (0.5 away, earlier on the
    # tie with nothing later); 101.0's slot already took 101.0. 106.0 dropped: 105.5 and 106.5
    # tie and the earlier one wins.
    seconds = _cut_seconds(104.0, drop=(102.0, 102.5, 106.0))
    assert len(seconds) == 14
    got = [seconds[i] for i in racing_cli.pick_model_frames(seconds, 104.0, 8)]
    assert got == [100.0, 101.0, 101.5, 103.0, 104.0, 105.0, 105.5, 107.0]
    # A slot with no frame within half a second is skipped, so fewer than N are sent.
    holes = _cut_seconds(104.0, drop=(101.5, 102.0, 102.5, 105.5, 106.0, 106.5))
    got = [holes[i] for i in racing_cli.pick_model_frames(holes, 104.0, 8)]
    assert got == [100.0, 101.0, 103.0, 104.0, 105.0, 107.0]


def test_pick_model_frames_a_tie_goes_to_the_earlier_frame() -> None:
    seconds = [99.5, 100.5, 101.5]
    assert racing_cli.pick_model_frames(seconds, 104.0, 1) == [0]
    assert racing_cli.pick_model_frames([100.5, 99.5, 101.5], 104.0, 1) == [1]


def test_pick_model_frames_n_at_least_the_cut_sends_all_and_n_one_sends_one() -> None:
    seconds = _cut_seconds(50.0)
    assert racing_cli.pick_model_frames(seconds, 50.0, 17) == list(range(17))
    assert racing_cli.pick_model_frames(seconds, 50.0, 40) == list(range(17))
    assert racing_cli.pick_model_frames(seconds[:5], 50.0, 8) == list(range(5))
    assert racing_cli.pick_model_frames(seconds, 50.0, 1) == [0]
    with pytest.raises(racing_cli.RacingCliError, match="at least 1"):
        racing_cli.pick_model_frames(seconds, 50.0, 0)


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_images_below_one_is_refused(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    out = tmp_path / "rule.jsonl"
    extra = ("--masks", CLI_FIXTURES / "masks.json", "--model", "fake", "--images", bad)
    assert judge(world, out, *extra, stage="rule") == 2
    assert f"--images {bad}" in capsys.readouterr().err and not out.exists()


@needs_ffmpeg
def test_rule_stage_sends_eight_images_and_replays(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_model(monkeypatch)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", "fake") == 0
    row = by_id(out)["1"]
    call = record.read_bundle(out, row["record"])["inputs"]["model_call"]
    assert call["images"] == 8 and len(call["frame_sha256"]) == 8
    assert "frame 1: stream second" in call["prompt"] and "frame 9:" not in call["prompt"]
    entries = [json.loads(p.read_text("utf-8")) for p in (tmp_path / "ledger").glob("*.json")]
    assert len(entries) == 3
    assert all(e["image_shas"] == call["frame_sha256"] for e in entries)
    _no_client(monkeypatch)
    monkeypatch.delenv("FAULTLINE_FAKE_MODEL")
    again = tmp_path / "replayed.jsonl"
    assert run("replay", out, "--out", again) == 0
    assert again.read_bytes() == out.read_bytes()


@needs_ffmpeg
def test_an_old_bundle_without_images_still_replays(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_model(monkeypatch)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", "fake", "--images", "17") == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    for row in rows:
        bundle = record.read_bundle(out, row["record"])
        call = bundle["inputs"].get("model_call")
        if call is None:
            continue
        assert call.pop("images") == 17 and len(call["frame_sha256"]) == 17
        sha = record.record_hash(bundle)
        record.write_bundle(out, sha, bundle)
        row["record"] = sha
    record.write_lines_atomic(out, rows)
    old = out.read_bytes()
    _no_client(monkeypatch)
    monkeypatch.delenv("FAULTLINE_FAKE_MODEL")
    again = tmp_path / "replayed.jsonl"
    assert run("replay", out, "--out", again) == 0
    assert again.read_bytes() == old


@needs_ffmpeg
def test_rule_replay_refuses_a_missing_ledger_entry(
    video_world: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_model(monkeypatch)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", "fake") == 0
    keys = record.read_bundle(out, by_id(out)["1"]["record"])["inputs"]["ledger_keys"]
    (tmp_path / "ledger" / f"{keys[1]}.json").unlink()
    _no_client(monkeypatch)
    assert run("replay", out, "--out", tmp_path / "again.jsonl") == 2
    assert "never calls the model" in capsys.readouterr().err


@needs_ffmpeg
def test_the_fake_model_never_runs_under_a_real_name(
    video_world: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_model(monkeypatch)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", MODEL) == 2
    assert "only --model fake" in capsys.readouterr().err
    monkeypatch.delenv("FAULTLINE_FAKE_MODEL")
    assert stage_run(video_world, out, "rule", "--model", "fake") == 2
    assert "needs FAULTLINE_FAKE_MODEL=1" in capsys.readouterr().err
    assert not out.exists()


@needs_ffmpeg
def test_a_held_ledger_lock_refuses_and_another_ledger_needs_a_cap(
    video_world: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _fake_model(monkeypatch)
    out = tmp_path / "rule.jsonl"
    (tmp_path / "ledger").mkdir()
    lock = tmp_path / "ledger" / racing_cli.LOCK_NAME
    lock.write_text("1234\n", encoding="utf-8")
    assert stage_run(video_world, out, "rule", "--model", "fake") == 2
    assert "ledger is locked" in capsys.readouterr().err
    assert lock.exists() and calls == [] and not out.exists()
    lock.unlink()

    other = tmp_path / "elsewhere"
    assert stage_run(video_world, out, "rule", "--model", "fake", "--ledger", other) == 2
    assert "FAULTLINE_CAP_USD" in capsys.readouterr().err
    monkeypatch.setenv("FAULTLINE_CAP_USD", "5.00")
    assert stage_run(video_world, out, "rule", "--model", "fake", "--ledger", other) == 0
    assert len(list(other.glob("*.json"))) == 3 and not (other / racing_cli.LOCK_NAME).exists()


@needs_ffmpeg
def test_the_lock_is_released_when_a_run_fails(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Scripted(lambda _k: _reply("3"), cache="hit")
    _real_model(monkeypatch, tmp_path, fake)
    assert stage_run(video_world, tmp_path / "rule.jsonl", "rule", "--model", MODEL) == 2
    assert not (tmp_path / "ledger" / racing_cli.LOCK_NAME).exists()


@needs_ffmpeg
def test_the_pattern_schema_form_is_sent_and_recorded(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Scripted(lambda _k: _reply("3"))
    _real_model(monkeypatch, tmp_path, fake)
    out = tmp_path / "rule.jsonl"
    extra = ("--model", MODEL, "--arm", "2", "--schema-form", "pattern")
    assert stage_run(video_world, out, "rule", *extra) == 0
    sent = fake.calls[0]["response_format"]["json_schema"]["schema"]
    assert "pattern" in sent["properties"]["offender"]["anyOf"][0]
    call = record.read_bundle(out, by_id(out)["1"]["record"])["inputs"]["model_call"]
    assert call["schema_form"] == "pattern"


class _Scripted:
    """A fake transport: `answer(k)` gives the reply text of call k (from 0)."""

    def __init__(self, answer: Any, cache: str | None = "miss") -> None:
        self.answer = answer
        self.cache = cache
        self.calls: list[dict[str, Any]] = []
        self._http = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        text = self.answer(len(self.calls) - 1)
        body = {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 120},
        }
        headers = {client.CACHE_HEADER: self.cache} if self.cache else None
        return httpx.Response(200, json=body, headers=headers)

    def __call__(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> Any:
        self.calls.append(payload)
        return self._http.post(url, headers=headers, json=payload)


def _real_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake: _Scripted) -> None:
    for name in ("MODEL_API_KEY", "MODEL_API_BASE", "FAULTLINE_FAKE_MODEL", "FAULTLINE_CAP_USD"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "test.env"
    env_file.write_text("MODEL_API_KEY=test-key-not-real\nMODEL_API_BASE=http://127.0.0.1:9/v1\n")
    monkeypatch.setenv("STEWARD_ENV_FILE", str(env_file))
    monkeypatch.setattr(client, "CLIENT", fake)


def _reply(offender: str | None, verdict: str = "penalty", reason: str = REASON) -> str:
    return json.dumps(
        {"offender": offender, "verdict": verdict, "reason": reason, "frames_used": ["frame 5"]}
    )


@needs_ffmpeg
def test_an_agreed_penalty_sets_the_offender(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Scripted(lambda _k: "```json\n" + _reply("3") + "\n```")
    _real_model(monkeypatch, tmp_path, fake)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", MODEL) == 0
    assert len(fake.calls) == 3 and all("response_format" not in c for c in fake.calls)
    tails = [c["messages"][-1]["content"][1]["text"] for c in fake.calls]
    assert tails == [f"Request reference: 1-run{k}" for k in (1, 2, 3)]
    one = by_id(out)["1"]
    assert "3" in one["candidates"]
    assert one["model_read"]["agreed"] is True and one["model_read"]["verdict"] == "penalty"
    assert one["model_read"]["source"] == "model"
    assert one["offender"] == "3"
    assert one["verdict"] == "steward_review"
    images = [p for p in fake.calls[0]["messages"][-1]["content"] if p["type"] == "image_url"]
    assert len(images) == racing_cli.DEFAULT_IMAGES == 8


@needs_ffmpeg
def test_a_disagreement_leaves_the_offender_null(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Scripted(lambda k: _reply("3" if k % 2 == 0 else "2"))
    _real_model(monkeypatch, tmp_path, fake)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", MODEL, "--arm", "2") == 0
    assert all(c["response_format"]["json_schema"]["strict"] for c in fake.calls)
    one = by_id(out)["1"]
    assert one["model_read"]["agreed"] is False and one["model_read"]["offender"] is None
    assert one["offender"] is None


@needs_ffmpeg
def test_a_planted_name_in_a_reply_never_reaches_the_line(
    video_world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = REASON[:-1] + ", and Fenwhistle braked late."
    fake = _Scripted(lambda k: _reply("3", reason=named if k == 1 else REASON))
    _real_model(monkeypatch, tmp_path, fake)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", MODEL) == 0
    one = by_id(out)["1"]
    assert one["model_read"]["lint_hits"] == 1 and one["model_read"]["agreed"] is False
    assert one["offender"] is None
    assert "fenwhistle" not in _written_text(out)
    hits = sorted(
        json.loads(p.read_text("utf-8"))["name_hit"] for p in (tmp_path / "ledger").glob("*.json")
    )
    assert hits == [False, False, True]


@needs_ffmpeg
@pytest.mark.parametrize("word", ["hit", None])
def test_a_reply_not_said_fresh_is_stored_then_stops_the_rule_stage(
    video_world: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    word: str | None,
) -> None:
    fake = _Scripted(lambda _k: _reply("3"), cache=word)
    _real_model(monkeypatch, tmp_path, fake)
    out = tmp_path / "rule.jsonl"
    assert stage_run(video_world, out, "rule", "--model", MODEL) == 2
    err = capsys.readouterr().err
    assert "1-run1" in err and "fresh" in err
    assert not out.exists()
    (entry,) = [json.loads(p.read_text("utf-8")) for p in (tmp_path / "ledger").glob("*.json")]
    assert entry["cached"] is (True if word == "hit" else None)  # kept, so its spend counts


# ---------------------------------------------------------------- masks are mandatory


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda m: m.update(default=[]), "non-empty list"),
        (lambda m: m.update(default=["drawbox=x=0:y=0:w=9:h=9:color=black"]), "filled drawbox"),
        (lambda m: m.update(default=["scale=10:10"]), "filled drawbox"),
        (lambda m: m.update(default=["drawbox=x=0:t=fill,drawtext=text=a:t=fill"]), "filled"),
        (lambda m: m["sessions"]["9000100/RACE"].append("null"), "filled drawbox"),
        (lambda m: m.pop("drop_layouts"), "drop_layouts is missing"),
        (lambda m: m.update(drop_layouts={}), "not a list"),
        (lambda m: m["drop_layouts"][0].update(probes=[]), "drop rule 0"),
        (lambda m: m["drop_layouts"][1].update(rgb_max=[0, 0]), "drop rule 1"),
    ],
)
def test_a_bad_masks_file_is_refused(
    world: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: Any,
    message: str,
) -> None:
    masks = json.loads((CLI_FIXTURES / "masks.json").read_text(encoding="utf-8"))
    change(masks)
    path = world["base"] / "masks-bad.json"
    path.write_text(json.dumps(masks), encoding="utf-8")
    out = tmp_path / "frames.jsonl"
    assert judge(world, out, "--masks", path, stage="frames") == 2
    assert message in capsys.readouterr().err
    assert not out.exists()


def test_an_explicit_empty_drop_layouts_is_allowed(world: dict[str, Path]) -> None:
    masks = json.loads((CLI_FIXTURES / "masks.json").read_text(encoding="utf-8"))
    masks["drop_layouts"] = []
    path = world["base"] / "masks-none.json"
    path.write_text(json.dumps(masks), encoding="utf-8")
    assert racing_cli._Masks(path).drop_layouts == []


# ---------------------------------------------------------------- core boundary

CORE_FILES = ("cli", "frames", "ruling", "client", "record", "ledger", "lint", "roster")
DOMAIN_WORDS = ("racing", "pitbot", "steward", "protest", "broadcast")
# Fixed names the core must keep: an env variable and a sibling repository's path.
ALLOWED_NAMES = ("STEWARD_ENV_FILE", "ai-steward")


@pytest.mark.parametrize("name", CORE_FILES)
def test_core_modules_import_no_adapter_and_have_no_domain_words(name: str) -> None:
    path = REPO / "src" / "faultline" / f"{name}.py"
    text = path.read_text(encoding="utf-8")
    assert not _imports_adapter(ast.parse(text))
    assert not CORE_WORDS.search(text), CORE_WORDS.search(text)
    for allowed in ALLOWED_NAMES:
        text = text.replace(allowed, "")
    for word in DOMAIN_WORDS:
        assert word not in text.casefold(), f"{name}.py holds {word!r}"


def test_the_domain_is_found_by_discovery() -> None:
    words = [word for word, _module in cli._domain_modules()]
    assert words == ["racing"]


def test_the_console_script_points_at_main() -> None:
    points = [e for e in metadata.entry_points(group="console_scripts") if e.name == "faultline"]
    assert len(points) == 1 and points[0].value == "faultline.cli:main"


def test_feed_fixture_is_gzip(world: dict[str, Path]) -> None:
    raw = (world["base"] / "replay-a.ndjson.gz").read_bytes()
    assert gzip.decompress(raw).startswith(b"{")
