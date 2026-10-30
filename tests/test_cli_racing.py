"""Tests for the `faultline` command line: racing limits, racing judge (locate) and replay.

Everything runs on synthetic data: the small feed of `tests/adapters/conftest.py` (made-up
cars "1" to "6", invented names "Test Driver A" to "F"), a league and six protests from
`tests/fixtures/racing/cli/`, and a one-rule pack, all written into `tmp_path` at test time.
"""

from __future__ import annotations

import ast
import dataclasses
import gzip
import json
import shutil
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from adapters.conftest import write_feed
from test_public_tree import CORE_WORDS, _imports_adapter

from faultline import cli, record
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
def test_later_stages_exit_non_zero(
    world: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str], stage: str
) -> None:
    out = tmp_path / "locate.jsonl"
    assert judge(world, out, stage=stage) != 0
    err = capsys.readouterr().err.strip()
    assert "later checkpoint" in err and stage in err
    assert len(err.splitlines()) == 1
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


# ---------------------------------------------------------------- core boundary


def test_core_cli_imports_no_adapter_and_has_no_domain_words() -> None:
    path = REPO / "src" / "faultline" / "cli.py"
    text = path.read_text(encoding="utf-8")
    assert not _imports_adapter(ast.parse(text))
    assert not CORE_WORDS.search(text)
    assert "racing" not in text.casefold() and "pitbot" not in text.casefold()


def test_the_domain_is_found_by_discovery() -> None:
    words = [word for word, _module in cli._domain_modules()]
    assert words == ["racing"]


def test_the_console_script_points_at_main() -> None:
    points = [e for e in metadata.entry_points(group="console_scripts") if e.name == "faultline"]
    assert len(points) == 1 and points[0].value == "faultline.cli:main"


def test_feed_fixture_is_gzip(world: dict[str, Path]) -> None:
    raw = (world["base"] / "replay-a.ndjson.gz").read_bytes()
    assert gzip.decompress(raw).startswith(b"{")
