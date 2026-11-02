"""The racing panel's data and live checks: `pitbot.bundle` and `pitbot.replay_one`.

Everything but the `private` tests runs on synthetic data: the small feed with the planted
invented names of `tests/test_cli_racing.py`, the league and reports of
`tests/fixtures/racing/cli/`, judged at the locate stage and ruled for the incident limit
into a temp racing folder laid out like the server's copy, plus a made-up truth table, a
made-up league name and a README holding only the lines the builder reads.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT
from test_cli_racing import CLI_FIXTURES, PLANTED_NAMES, _all_counters_shown, _frames

from adapters.conftest import write_feed
from faultline import cli
from faultline.adapters.pitbot import bundle, replay_one

SESSION_NUMBERS = ("9000100", "9000200", "9000999")
LEAGUE_NAME = "Quorvale Test League"
FILLER = [f"Invented Person {c}" for c in "ABCDEFGHIJ"]


def run(*argv: str | Path) -> int:
    return cli.main([str(a) for a in argv])


def _readme(path: Path, *, over: int, on_record: int, no_ruling: int, protests: int) -> Path:
    path.write_text(
        "\n".join(
            [
                "# made-up README",
                "",
                f"The model's read did not pass its mark: 0 of {protests} on both arms, "
                f"against a mark of {protests} of {protests}.",
                "Every agreed read that named a car named the right one, 0 of 0 on each arm.",
                "",
                "| Mark | Result | Pass mark | Verdict |",
                "|---|---|---|---|",
                "| Rule A, incident limit | 7 of 7 decisions found | 7 of 7 | pass |",
                "| Locator | 2 of 7 windows | 5 of 7 | fail |",
                "| Closed set | 8 of 10 | 7 of 10 | pass |",
                f"| Model's read, offender | 0 of {protests} on each arm | 8 of 8 | fail |",
                "| Replay | byte-identical | byte-identical | pass |",
                "| Spend | $1.76 on the metering proxy | $5 | pass |",
                "",
                f"- The incident limit also found {over} cars over the limit: {on_record} match a "
                f"ruling on record, and {no_ruling} are over the limit, no ruling on record.",
                "- On decision 18 the frames do not clearly show the contact.",
                "  One run named a car, and the gate kept it out.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _copy_record(src: Path, dest_dir: Path) -> None:
    shutil.copyfile(src, dest_dir / src.name)
    shutil.copytree(Path(f"{src}.record"), dest_dir / f"{src.name}.record")


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A racing folder as the server holds it, its private source folder, and a README."""
    card = bundle._card()
    monkeypatch.setattr(card, "feed_names", lambda data: sorted(PLANTED_NAMES.values()) + FILLER)
    racing = tmp_path / "racing"
    (racing / "feeds").mkdir(parents=True)
    write_feed(_frames(), racing / "feeds" / "replay-a.ndjson.gz")
    write_feed(_all_counters_shown(_frames()), racing / "feeds" / "replay-b.ndjson.gz")
    league = json.loads((CLI_FIXTURES / "league.json").read_text(encoding="utf-8"))
    for key, feed, short in (
        ("9000100/RACE", "replay-a", "Alpha"),
        ("9000200/RACE", "replay-b", "Beta"),
    ):
        league["sessions"][key].update(feed=f"feeds/{feed}.ndjson.gz", track_short=short)
    (racing / "league.json").write_text(json.dumps(league, indent=2), encoding="utf-8")
    reports = json.loads((CLI_FIXTURES / "reports.json").read_text(encoding="utf-8"))
    keep = [r for r in reports if r["id"] in ("1", "4", "10")]
    reports_path = tmp_path / "reports.jsonl"
    reports_path.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
    pack = tmp_path / "quorvale-pack"
    pack.mkdir()
    pack_json = {"name": LEAGUE_NAME, "version": "1", "domain": "racing"}
    (pack / "pack.json").write_text(json.dumps(pack_json), encoding="utf-8")
    (pack / "t1.md").write_text("---\nid: T1\ntitle: Contact\n---\nLeave room.\n", encoding="utf-8")

    monkeypatch.chdir(racing)  # the league's feed paths resolve from the racing folder
    for arm in (1, 2):
        out = racing / f"preds-arm{arm}.jsonl"
        assert run("racing", "judge", reports_path, "--league", "league.json", "--rules", pack,
                   "--out", out, "--stage", "locate") == 0  # fmt: skip
    assert run("racing", "limits", "--league", "league.json", "--out", racing / "limits.jsonl") == 0
    monkeypatch.chdir(tmp_path)

    source = tmp_path / "source"
    source.mkdir()
    for name in ("preds-arm1.jsonl", "preds-arm2.jsonl", "limits.jsonl"):
        _copy_record(racing / name, source)
    for key in league["sessions"]:
        feed = league["sessions"][key]["feed"]
        league["sessions"][key]["feed"] = str(racing / feed)
    (source / "league.json").write_text(json.dumps(league, indent=2), encoding="utf-8")
    ids = sorted({*(r["id"] for r in keep), "1", "11", "13", "14", "15", "16", "18", "23", "24",
                  "46"})  # fmt: skip
    truth = {
        "decisions": [
            {"id": i, "session": "9000100/RACE", "offender_sim": "2", "victim_sim": "1",
             "contact_te": 100, "duplicate_of": None, "verdict": "penalty"}
            for i in ids
        ]
    }  # fmt: skip
    (source / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps({"decisions": []}), encoding="utf-8")
    inputs = {"catalogue": str(catalogue), "pack_dir": str(pack)}
    (source / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")

    limits = [json.loads(t) for t in (racing / "limits.jsonl").read_text("utf-8").splitlines()]
    breaches = sum(1 for r in limits if r["verdict"] == "breach")
    contacts = [
        json.loads(t) for t in (racing / "preds-arm2.jsonl").read_text("utf-8").splitlines()
    ]
    readme = _readme(tmp_path / "README.md", over=breaches, on_record=0, no_ruling=breaches,
                     protests=len(contacts))  # fmt: skip
    return {"racing": racing, "source": source, "readme": readme, "out": tmp_path / "www"}


def build(site: dict[str, Path], out: Path | None = None) -> str:
    return bundle.build_racing(site["racing"], site["readme"], out or site["out"], site["source"])


def events(capsys: pytest.CaptureFixture[str], *argv: str | Path) -> tuple[int, list[dict]]:
    capsys.readouterr()
    code = replay_one.main([str(a) for a in argv])
    text = capsys.readouterr().out
    return code, [json.loads(line) for line in text.splitlines() if line.strip()]


def result(evs: list[dict[str, Any]]) -> dict[str, Any]:
    (res,) = [e for e in evs if e["event"] == "result"]
    return res


def stages(evs: list[dict[str, Any]]) -> list[str]:
    return [e["name"] for e in evs if e["event"] == "stage"]


# ---------------------------------------------------------------- racing.json


def test_racing_json_is_byte_identical_twice(site: dict[str, Path], tmp_path: Path) -> None:
    one, two = tmp_path / "o1", tmp_path / "o2"
    assert build(site, one) == build(site, two)
    assert (one / "racing.json").read_bytes() == (two / "racing.json").read_bytes()
    doc = json.loads((one / "racing.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and doc["limits_mode"] == "rerule"
    assert [p["id"] for p in doc["protests"]] == ["1", "4", "10"]
    p = doc["protests"][0]
    assert p["window"]["race"].startswith("Race ") and p["window"]["session"] == "RACE"
    assert all(c.startswith("car ") for c in p["candidates"])
    assert [r["arm"] for r in p["reads"]] == [1, 2]
    assert p["reads"][0]["model"] == "Muse Spark Open" and p["reads"][0]["where"] == "Baseten"
    assert p["reads"][1]["model"] == "Muse Spark 1.3" and p["reads"][1]["agreed"] is False
    assert p["steward_ruling"] == "penalty, car 2 (contact with car 1)"
    assert set(p["record"]) == {"arm1", "arm2"}
    assert doc["numbers"]["over_limit"]["readme_line"] == 15
    assert [r["id"] for r in doc["limits"]] == [f"s{i}" for i in range(1, len(doc["limits"]) + 1)]
    smap = json.loads((site["racing"] / bundle.SESSION_MAP).read_text(encoding="utf-8"))
    assert [s["label"] for s in smap["sessions"]] == ["Race 1 · RACE", "Race 2 · RACE"]
    assert not (one / bundle.SESSION_MAP).exists()  # the map stays beside the record


def test_no_session_number_or_name_in_any_output(
    site: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    build(site)
    texts = [p.read_text(encoding="utf-8") for p in site["out"].rglob("*") if p.is_file()]
    _, evs = events(capsys, "--racing", site["racing"], "--protest", "1")
    _, evs2 = events(capsys, "--racing", site["racing"], "--limits")
    texts += [json.dumps(e) for e in evs + evs2]
    blob = "\n".join(texts).casefold()
    for bad in (*SESSION_NUMBERS, LEAGUE_NAME, *PLANTED_NAMES.values()):
        for token in bad.casefold().split():
            if len(token) > 3 and token not in ("test", "league"):
                assert token not in blob, token


def test_a_planted_name_in_a_fact_refuses_and_writes_nothing(site: dict[str, Path]) -> None:
    for folder in (site["racing"], site["source"]):
        path = folder / "preds-arm2.jsonl"
        rows = [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["facts"] = [f"{PLANTED_NAMES['2']} closed on car 1."]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(bundle.BundleError):
        build(site)
    assert not (site["out"] / "racing.json").exists()


def test_a_copy_that_differs_from_the_source_refuses(site: dict[str, Path]) -> None:
    path = site["racing"] / "limits.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(bundle.BundleError, match="differs"):
        build(site)


def test_a_readme_count_the_data_disagrees_with_refuses(site: dict[str, Path]) -> None:
    text = site["readme"].read_text(encoding="utf-8")
    site["readme"].write_text(text.replace("also found ", "also found 1", 1), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="README line"):
        build(site)


def test_a_missing_readme_line_refuses(site: dict[str, Path]) -> None:
    text = site["readme"].read_text(encoding="utf-8")
    site["readme"].write_text(text.replace("| Locator |", "| Finder |"), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="lost a row"):
        build(site)


def test_the_real_readme_still_states_every_number() -> None:
    got = bundle.read_readme_numbers(REPO_ROOT / "README.md")
    assert set(bundle.README_NUMBERS) <= set(got["numbers"])
    assert set(bundle.SCOREBOARD_KEYS.values()) <= set(got["numbers"])
    assert got["numbers"]["over_limit"]["text"] == "29 cars over the limit"
    assert got["honesty"]["lines"][0].startswith("On decision 18")
    assert got["numbers"]["spend"]["text"] == "$1.76 spent"
    assert got["numbers"]["spend_mark"]["text"] == "$1.76 spent"


def test_limits_rows_carry_the_stated_incidents_and_limit(site: dict[str, Path]) -> None:
    build(site)
    doc = json.loads((site["out"] / "racing.json").read_text(encoding="utf-8"))
    league = json.loads((site["racing"] / "league.json").read_text(encoding="utf-8"))
    limits = {s["incident_limit"] for s in league["sessions"].values()}
    rows = doc["limits"]
    breaches = [r for r in rows if r["verdict"] == "breach"]
    assert breaches
    for r in breaches:
        assert f"on {r['incidents']} incident points" in r["evidence"]
        assert r["limit"] in limits and f"the limit of {r['limit']}" in r["evidence"]
        assert r["incidents"] > r["limit"]
    for r in rows:
        assert set(r) >= {"incidents", "limit"}
        if "incident points" not in r["evidence"]:
            assert r["incidents"] is None


def test_a_line_stating_no_numbers_gives_nulls(site: dict[str, Path]) -> None:
    for folder in (site["racing"], site["source"]):
        path = folder / "limits.jsonl"
        rows = [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
        i = next(k for k, r in enumerate(rows) if r["verdict"] == "breach")
        rows[i]["evidence"] = f"Car {rows[i]['offender']} ended the session over its limit."
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="total"):  # a breach must state its total
        build(site)
    score = bundle._card().score
    session = {"incident_limit": 20}
    none = {"evidence": "The counter is not shown, so nothing can be checked."}
    assert bundle._stated_numbers(score, none, session) == {"incidents": None, "limit": None}
    unable = {"evidence": "Shown for 0 of 22 cars, so the limit of 20 cannot be checked."}
    assert bundle._stated_numbers(score, unable, session) == {"incidents": None, "limit": 20}


def test_a_stated_limit_the_session_does_not_hold_refuses(site: dict[str, Path]) -> None:
    for folder in (site["racing"], site["source"]):
        path = folder / "limits.jsonl"
        text = path.read_text(encoding="utf-8")
        assert "the limit of 2 " in text
        path.write_text(text.replace("the limit of 2 ", "the limit of 3 ", 1), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="limit its session does not hold"):
        build(site)


def test_no_served_text_holds_a_tooling_word(site: dict[str, Path]) -> None:
    # The fixture README's Spend row says "on the metering proxy", as the real one does.
    assert "proxy" in site["readme"].read_text(encoding="utf-8")
    build(site)
    doc = json.loads((site["out"] / "racing.json").read_text(encoding="utf-8"))
    served = list(bundle._texts(doc))
    assert served and not [t for t in served if "proxy" in t.casefold()]
    assert doc["numbers"]["spend"]["text"] == "$1.76 spent"


def test_limits_mode_follows_the_feeds(site: dict[str, Path]) -> None:
    assert bundle.limits_mode(site["racing"]) == "rerule"
    (site["racing"] / "feeds" / "replay-b.ndjson.gz").unlink()
    assert bundle.limits_mode(site["racing"]) == "checked"
    build(site)
    doc = json.loads((site["out"] / "racing.json").read_text(encoding="utf-8"))
    assert doc["limits_mode"] == "checked"


# ---------------------------------------------------------------- replay_one: protests


def test_protest_matches_faultline_replay(
    site: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build(site)
    code, evs = events(capsys, "--racing", site["racing"], "--protest", "10")
    assert code == 0
    assert stages(evs) == ["start", "record", "rebuild", "seal"]
    res = result(evs)
    assert res["match"] is True and res["label"] == "Protest 10"
    assert res["record_rebuilt"] == res["record_shipped"]
    for arm in (1, 2):
        preds = site["racing"] / f"preds-arm{arm}.jsonl"
        again = tmp_path / f"replay-arm{arm}.jsonl"
        assert run("replay", preds, "--out", again) == 0
        row = next(json.loads(t) for t in again.read_text("utf-8").splitlines()
                   if json.loads(t)["id"] == "10")  # fmt: skip
        assert res["record_shipped"][f"arm{arm}"] == row["record"]
        if arm == 2:
            assert res["rulings"] == [{"rule": row["rule"], "verdict": row["verdict"]}]


def test_a_tampered_bundle_gives_match_false(
    site: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    build(site)
    preds = site["racing"] / "preds-arm2.jsonl"
    row = json.loads(preds.read_text(encoding="utf-8").splitlines()[0])
    path = Path(f"{preds}.record") / f"{row['record']}.json"
    bundle_obj = json.loads(path.read_text(encoding="utf-8"))
    bundle_obj["ruling"]["evidence"] += " Changed."
    path.write_text(json.dumps(bundle_obj), encoding="utf-8")
    code, evs = events(capsys, "--racing", site["racing"], "--protest", row["id"])
    res = result(evs)
    assert code == 0 and res["match"] is False and res["why"] == replay_one.NOT_REBUILT
    assert [x["match"] for x in res["lines"]] == [True, False]
    assert res["record_rebuilt"]["arm2"] is None


def test_an_unknown_protest_is_an_error(
    site: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    code, evs = events(capsys, "--racing", site["racing"], "--protest", "999")
    assert code == 2 and evs[-1]["event"] == "error"


# ---------------------------------------------------------------- replay_one: limits


def test_limits_rerule_matches_faultline_racing_limits(
    site: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    build(site)
    monkeypatch.chdir(site["racing"])
    fresh = tmp_path / "fresh.jsonl"
    assert run("racing", "limits", "--league", "league.json", "--out", fresh) == 0
    monkeypatch.chdir(tmp_path)
    assert fresh.read_bytes() == (site["racing"] / "limits.jsonl").read_bytes()
    code, evs = events(capsys, "--racing", site["racing"], "--limits")
    res = result(evs)
    assert code == 0 and res["mode"] == "rerule" and res["match"] is True
    assert res["record_rebuilt"] == hashlib.sha256(fresh.read_bytes()).hexdigest()
    lines = [e for e in evs if e["event"] == "line"]
    assert lines and all(e["match"] for e in lines)
    assert all(e["id"].startswith("Race ") for e in lines)
    assert stages(evs) == ["start", "record", "rebuild", "seal"]
    assert Path.cwd() == tmp_path  # the working folder is put back


def test_limits_checked_without_feeds_and_a_tampered_bundle(
    site: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    build(site)
    shutil.rmtree(site["racing"] / "feeds")
    code, evs = events(capsys, "--racing", site["racing"], "--limits")
    res = result(evs)
    assert code == 0 and res["mode"] == "checked" and res["match"] is True
    assert res["record_rebuilt"] == res["record_shipped"]

    stored = site["racing"] / "limits.jsonl"
    row = json.loads(stored.read_text(encoding="utf-8").splitlines()[0])
    path = Path(f"{stored}.record") / f"{row['record']}.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["ruling"]["evidence"] += " Changed."
    path.write_text(json.dumps(obj), encoding="utf-8")
    code, evs = events(capsys, "--racing", site["racing"], "--limits")
    res = result(evs)
    assert code == 0 and res["match"] is False
    lines = [e for e in evs if e["event"] == "line"]
    assert [e["match"] for e in lines].count(False) == 1


def test_limits_rerule_on_a_changed_stored_line_gives_match_false(
    site: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    build(site)
    stored = site["racing"] / "limits.jsonl"
    stored.write_text(stored.read_text(encoding="utf-8").replace("incident", "Incident", 1),
                      encoding="utf-8")  # fmt: skip
    _, evs = events(capsys, "--racing", site["racing"], "--limits")
    assert result(evs)["match"] is False


def test_the_bundle_command_writes_racing_json(site: dict[str, Path]) -> None:
    assert run("racing", "bundle", "--racing", site["racing"], "--source", site["source"],
               "--readme", site["readme"], "--out", site["out"]) == 0  # fmt: skip
    assert (site["out"] / "racing.json").is_file()


# ---------------------------------------------------------------- the private record

SITE = REPO_ROOT / "data" / "site" / "racing"
ORIG = REPO_ROOT / "data" / "racing"


def _need_private() -> None:
    if not (SITE / "preds-arm2.jsonl").is_file() or not (ORIG / "truth.json").is_file():
        pytest.skip("private racing record absent")


@pytest.mark.private
def test_private_racing_json(tmp_path: Path) -> None:
    _need_private()
    limits = ORIG / "limits-a.jsonl"
    one = bundle.build_racing(SITE, REPO_ROOT / "README.md", tmp_path / "a", ORIG, limits)
    two = bundle.build_racing(SITE, REPO_ROOT / "README.md", tmp_path / "b", ORIG, limits)
    assert one == two
    text = (tmp_path / "a" / "racing.json").read_text(encoding="utf-8")
    doc = json.loads(text)
    assert len(doc["protests"]) == 8
    league = json.loads((SITE / "league.json").read_text(encoding="utf-8"))
    for key in league["sessions"]:
        assert key.partition("/")[0] not in text


@pytest.mark.private
@pytest.mark.parametrize("argv", [("--protest", "1"), ("--protest", "18"), ("--limits",)])
def test_private_replay_one(argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> None:
    _need_private()
    if not (SITE / bundle.SESSION_MAP).is_file() and "--limits" in argv:
        pytest.skip("session map not built yet")
    code, evs = events(capsys, "--racing", SITE, *argv)
    assert code == 0 and result(evs)["match"] is True
