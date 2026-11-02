"""scripts/site_sweep.py: each planted leak fails the sweep; a clean fixture passes and is stamped.

The fixture bundle and page live in `tests/fixtures/site_sweep/`. Frames (JPEG) are written into
the temp copy by the test, never committed. The names source (league file, feed, pack) is
written into the temp folder too, with made-up names only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import site_sweep as sweep  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "site_sweep"
LEAGUE_NAME = "Testline Racing League"
DRIVERS = [
    "Quillon Fakename",
    "Bryn Nullsworth",
    "Cato Placeholt",
    "Dara Mockwell",
    "Edda Stubbings",
    "Fenn Dummery",
    "Gale Notreal",
    "Hollis Fixtureson",
    "Ines Madeupova",
    "Jory Testcase",
    "Kael Pretendo",
]
SESSION = "9100001"
CUST_ID = "7700001"
STREAM = "stream-9100001.mp4"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + bytes(range(64)) + b"\xff\xd9"
HAS_GITLEAKS = shutil.which("gitleaks") is not None
needs_gitleaks = pytest.mark.skipif(not HAS_GITLEAKS, reason="gitleaks is not installed")


def _frame(te: int) -> dict[str, object]:
    positions = [
        {"carIdx": i, "custId": 9000000 + i, "name": n, "num": str(i), "pct": 0.5, "pos": i}
        for i, n in enumerate(DRIVERS, start=1)
    ]
    return {
        "flag": "green",
        "leaderLap": 1,
        "positions": positions,
        "rows": [],
        "session": "RACE",
        "timeElapsed": te,
        "track": "Thruxton Circuit",
    }


def _names_dir(root: Path) -> Path:
    names = root / "names"
    (names / "testline-pack").mkdir(parents=True)
    feed = "\n".join(json.dumps(_frame(te)) for te in (0, 1, 2)) + "\n"
    (names / "feed.ndjson").write_text(feed, encoding="utf-8")
    league = {
        "pack": {"rule_id": "T1"},
        "number_map": {
            "entries": [
                {
                    "cust_id": CUST_ID,
                    "league_num": "5",
                    "rule": "fake",
                    "sim_nums": {f"{SESSION}/RACE": "5"},
                }
            ],
            "rule": "fake",
        },
        "sessions": {
            f"{SESSION}/RACE": {
                "clause": "9.2.1",
                "incident_limit": 8,
                "feed": "feed.ndjson",
                "session": "RACE",
                "stream": f"D:/nowhere/{STREAM}",
            }
        },
    }
    (names / "league.json").write_text(json.dumps(league), encoding="utf-8")
    (names / "inputs.json").write_text(json.dumps({"pack_dir": "testline-pack"}), encoding="utf-8")
    (names / "testline-pack" / "pack.json").write_text(
        json.dumps({"name": LEAGUE_NAME}), encoding="utf-8"
    )
    return names


class Site:
    def __init__(self, root: Path) -> None:
        shutil.copytree(FIXTURE, root / "fx")
        self.page = root / "fx" / "page"
        self.bundle = self.page / "data"
        self.readme = root / "fx" / "README.md"
        self.names = _names_dir(root)
        frames = self.bundle / "frames"
        manifest = []
        for clip, name in (("clip_breach_01", "poster.jpg"), ("real_aisle_01", "3.jpg")):
            (frames / clip).mkdir(parents=True)
            data = JPEG + clip.encode()
            (frames / clip / name).write_bytes(data)
            manifest.append(
                {
                    "file": f"{clip}/{name}",
                    "clip": clip,
                    "frame": 3,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        (frames / "frames.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.set_blurred(True)

    def set_blurred(self, checked: bool) -> None:
        blurred = {"frames": [{"file": "real_aisle_01/3.jpg", "checked": checked}]}
        (self.bundle / "frames" / "blurred.json").write_text(json.dumps(blurred), encoding="utf-8")

    def run(self, gitleaks: str = "gitleaks") -> list[sweep.Failure]:
        return sweep.sweep(self.bundle, self.page, self.names, self.readme, gitleaks)

    def main(self) -> int:
        return sweep.main(
            [
                "--bundle",
                str(self.bundle),
                "--page",
                str(self.page),
                "--names",
                str(self.names),
                "--readme",
                str(self.readme),
            ]
        )

    def edit_json(self, rel: str, key: str, value: object) -> None:
        path = self.bundle / rel
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc[key] = value
        path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def site(tmp_path: Path) -> Site:
    return Site(tmp_path)


def _checks(failures: list[sweep.Failure]) -> set[int]:
    return {f.check for f in failures}


# ---------------------------------------------------------------- the clean fixture


@needs_gitleaks
def test_clean_fixture_passes_and_is_stamped(site: Site) -> None:
    assert [str(f) for f in site.run()] == []
    assert site.main() == 0
    stamp = site.bundle / f".sweep-{sweep.bundle_sha256(site.bundle)}.ok"
    assert stamp.is_file()
    body = json.loads(stamp.read_text(encoding="utf-8"))
    assert body["bundle_sha256"] == sweep.bundle_sha256(site.bundle)


def test_sweep_reads_every_file_in_the_fixture(site: Site) -> None:
    served = {f.rel for f in sweep.served_files(site.page, site.bundle)}
    on_disk = {p.relative_to(site.page).as_posix() for p in site.page.rglob("*") if p.is_file()}
    assert served == on_disk
    assert "data/frames/real_aisle_01/3.jpg" in served


def test_the_fixture_names_source_gives_names(site: Site) -> None:
    names = sweep.gather_names(site.names)
    assert "Quillon Fakename" in names.names
    assert LEAGUE_NAME in names.league
    assert {SESSION, CUST_ID, STREAM}.issubset(names.racing_ids)


# ---------------------------------------------------------------- the stamp key


def test_a_stamp_file_does_not_change_the_bundle_hash(site: Site) -> None:
    before = sweep.bundle_sha256(site.bundle)
    (site.bundle / f".sweep-{before}.ok").write_text("{}", encoding="utf-8")
    (site.bundle / ".sweep-0000.ok").write_text("old", encoding="utf-8")
    assert sweep.bundle_sha256(site.bundle) == before


def test_the_bundle_hash_follows_the_contract(site: Site) -> None:
    lines = sorted(
        f"{p.relative_to(site.bundle).as_posix()}\t{hashlib.sha256(p.read_bytes()).hexdigest()}\n"
        for p in site.bundle.rglob("*")
        if p.is_file()
    )
    expect = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert sweep.bundle_sha256(site.bundle) == expect
    (site.bundle / "clips" / "real_aisle_01.json").write_text("{}", encoding="utf-8")
    assert sweep.bundle_sha256(site.bundle) != expect


# ---------------------------------------------------------------- planted leaks


def _text_files(site: Site) -> list[Path]:
    return [
        p for p in sorted(site.page.rglob("*")) if p.suffix in {".html", ".js", ".css", ".json"}
    ]


def _plant(path: Path, words: str) -> None:
    if path.suffix == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            doc["planted"] = words
        else:
            doc.append({"planted": words})
        path.write_text(json.dumps(doc), encoding="utf-8")
    elif path.suffix == ".html":
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("</body>", f"<p>{words}</p></body>"), encoding="utf-8")
    elif path.suffix == ".css":
        path.write_text(path.read_text(encoding="utf-8") + f"/* {words} */\n", encoding="utf-8")
    else:
        path.write_text(path.read_text(encoding="utf-8") + f"// {words}\n", encoding="utf-8")


@needs_gitleaks
def test_a_tooling_word_in_any_served_file_fails(site: Site) -> None:
    for path in _text_files(site):
        original = path.read_bytes()
        _plant(path, "Made with Claude")
        failures = site.run()
        assert 2 in _checks(failures), path.name
        assert site.main() == 1
        path.write_bytes(original)
    assert site.run() == []


@needs_gitleaks
@pytest.mark.parametrize(
    "planted", [LEAGUE_NAME, "Quillon Fakename", "Nullsworth", "TestlineRacingLeague"]
)
def test_a_league_or_driver_name_fails_and_is_never_printed(
    site: Site, planted: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(site.bundle / "clips" / "clip_breach_01.json", f"Called by {planted}.")
    assert 1 in _checks(site.run())
    assert site.main() == 1
    out = capsys.readouterr()
    assert planted not in out.out + out.err
    assert not list(site.bundle.glob(".sweep-*.ok"))


@needs_gitleaks
@pytest.mark.parametrize("planted", [SESSION, CUST_ID, STREAM])
def test_a_session_number_customer_id_or_stream_name_fails(site: Site, planted: str) -> None:
    _plant(site.bundle / "racing.json", f"from {planted}")
    assert 5 in _checks(site.run())


@needs_gitleaks
def test_a_number_off_its_readme_line_fails(site: Site) -> None:
    site.edit_json(
        "index.json", "numbers", {"breach_found": {"text": "13 of 14", "readme_line": 3}}
    )
    assert 4 in _checks(site.run())


@needs_gitleaks
def test_an_uncited_number_in_the_html_fails(site: Site) -> None:
    _plant(site.page / "index.html", "Rules on 99 clips.")
    assert 4 in _checks(site.run())


@needs_gitleaks
def test_a_graded_hash_line_still_zero_fails(site: Site) -> None:
    site.edit_json(
        "index.json", "graded_replay", {"lines": 26, "sha256": "43afe3f7", "readme_line": 0}
    )
    assert 4 in _checks(site.run())


@needs_gitleaks
def test_an_unblurred_real_frame_fails(site: Site) -> None:
    site.set_blurred(False)
    failures = site.run()
    assert [f.check for f in failures] == [6]
    assert "real-footage" in failures[0].message


@needs_gitleaks
def test_an_image_not_in_the_manifest_fails(site: Site) -> None:
    (site.page / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(32))
    assert 6 in _checks(site.run())


@needs_gitleaks
def test_a_words_block_without_its_model_fails(site: Site) -> None:
    path = site.bundle / "clips" / "clip_breach_01.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["rulings"][0]["words"]["note"]["model"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert 5 in _checks(site.run())


@needs_gitleaks
def test_an_open_weight_line_not_verbatim_fails(site: Site) -> None:
    site.edit_json("index.json", "open_weight_line", "Muse Spark Open is open.")
    assert 5 in _checks(site.run())


@needs_gitleaks
def test_a_banned_phrase_fails(site: Site) -> None:
    _plant(site.page / "index.html", "A " + "co" + "ach for your laps.")
    assert 3 in _checks(site.run())


@needs_gitleaks
def test_a_key_with_a_value_or_an_env_file_fails(site: Site) -> None:
    _plant(site.page / "app.js", 'const MODEL_API_KEY = "abcd1234efgh5678ijkl";')
    assert 7 in _checks(site.run())


@needs_gitleaks
def test_an_env_file_fails(site: Site) -> None:
    (site.bundle / ".env").write_text("NOTHING=here\n", encoding="utf-8")
    assert 7 in _checks(site.run())


# ---------------------------------------------------------------- fail closed


def test_a_missing_names_source_fails_closed(
    site: Site, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(site.names)
    with pytest.raises(sweep.SweepError):
        site.run()
    assert site.main() == 2
    assert "names source is missing" in capsys.readouterr().err
    assert not list(site.bundle.glob(".sweep-*.ok"))


def test_a_missing_racing_bundle_fails_closed(
    site: Site, capsys: pytest.CaptureFixture[str]
) -> None:
    (site.bundle / "racing.json").unlink()
    with pytest.raises(sweep.SweepError, match="no racing.json"):
        site.run()
    assert site.main() == 2
    assert "no racing.json" in capsys.readouterr().err
    assert not list(site.bundle.glob(".sweep-*.ok"))


def test_a_missing_league_file_fails_closed(site: Site) -> None:
    (site.names / "league.json").unlink()
    with pytest.raises(sweep.SweepError, match="names source is missing"):
        site.run()


def test_missing_gitleaks_fails_closed(site: Site) -> None:
    with pytest.raises(sweep.SweepError, match="gitleaks"):
        site.run(gitleaks="no-such-gitleaks-here")


def test_gitleaks_refuses_a_folder_holding_a_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert sweep._scan_root_ok(tmp_path) is not None
    assert sweep._scan_root_ok(sweep.REPO) is not None


@needs_gitleaks
def test_a_failed_sweep_removes_an_old_stamp_for_the_same_bundle(site: Site) -> None:
    assert site.main() == 0
    (site.names / "inputs.json").unlink()
    assert site.main() == 2
    assert not list(site.bundle.glob(".sweep-*.ok"))
