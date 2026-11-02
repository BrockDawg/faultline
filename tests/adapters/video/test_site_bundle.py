"""The live page's bundle: byte-identical twice, the schema's keys, the shipped three built from
demo/record/ alone (runs on a clone), every README number on its line, a graded hash with no README
line refused, no clip twice, no host path anywhere in what it writes, frames from the manifest, and
model words only where they pass the lint beside their own ruling. The graded and real roots are
checked on this machine only (private)."""

import json
import re
import shutil
from pathlib import Path

import pytest

from faultline.adapters.video import bundle, cli

ROOT = Path(__file__).resolve().parents[3]
SHIPPED = ROOT / "demo" / "record"
README = ROOT / "README.md"
SITE = ROOT / "data" / "site"
SOURCES = SITE / "sources.json"
SHIPPED_SHA = "d991b59e6768a1f6b77bdd0fd0c4c6fb45afbe9d837bdfc9abab0fbfaaff7010"

INDEX_KEYS = {
    "schema",
    "featured",
    "groups",
    "clips",
    "numbers",
    "models",
    "open_weight_line",
    "graded_replay",
    "shipped_replay",
}
CLIP_KEYS = {"schema", "id", "entry", "record", "root", "kind", "live", "rulings"}
RULING_KEYS = {
    "rule",
    "title",
    "verdict",
    "decided_by",
    "measurement",
    "missing_fact",
    "lacks",
    "pack_words",
    "frames",
    "frames_source",
    "words",
}


def _sources(tmp: Path, **extra) -> Path:
    s = {
        "schema": 1,
        "roots": {"shipped": {"preds": str(SHIPPED / "preds.jsonl"), "set_sha256": SHIPPED_SHA}},
    }
    s.update(extra)
    p = tmp / "sources.json"
    p.write_text(json.dumps(s), encoding="utf-8")
    return p


def _files(d: Path) -> dict[str, bytes]:
    return {
        p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()
    }


def _host_paths(record: Path) -> set[str]:
    out = set()
    for e in (record / "entries").glob("fl-*.json"):
        if e.name.endswith(".words.json"):
            continue
        m = json.loads(e.read_text(encoding="utf-8"))
        for d in (m.get("host_paths") or {}, m.get("item") or {}):
            for k in ("clip", "site", "rules_dir"):
                if isinstance(d.get(k), str):
                    out.add(d[k])
    return out


def test_shipped_three_from_demo_record_alone(tmp_path):
    out = tmp_path / "data"
    sha = bundle.build_bundle(_sources(tmp_path), out)
    assert re.fullmatch(r"[0-9a-f]{64}", sha)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert set(index) == INDEX_KEYS
    assert index["featured"] == bundle.FEATURED
    assert [c["id"] for c in index["clips"]] == bundle.FEATURED
    assert {c["group"] for c in index["clips"]} == {"shipped"}
    assert [g["id"] for g in index["groups"]] == ["shipped"]
    assert index["graded_replay"] is None
    assert index["shipped_replay"] == {"lines": 3, "sha256": SHIPPED_SHA, "readme_line": 800}
    assert index["numbers"]["breach_found"] == {"text": "12 of 14", "readme_line": 275}
    assert index["numbers"]["shift_rulings"]["text"] == "240"
    assert "meta-models/muse-spark-open-1026" in index["open_weight_line"]
    hints = {c["id"]: c["hint"] for c in index["clips"]}
    assert hints == {
        "blind_corner_no_vest_07": "breach",
        "spotter_ahead_01": "clear",
        "idle_empty_aisle_40": "mixed",
    }
    preds = {
        json.loads(x)["id"]: json.loads(x)
        for x in (SHIPPED / "preds.jsonl").read_text(encoding="utf-8").splitlines()
    }
    for cid in bundle.FEATURED:
        clip = json.loads((out / "clips" / f"{cid}.json").read_text(encoding="utf-8"))
        assert set(clip) == CLIP_KEYS
        assert clip["record"] == preds[cid]["record"]
        assert [r["verdict"] for r in clip["rulings"]] == [
            r["verdict"] for r in preds[cid]["rulings"]
        ]
        for r in clip["rulings"]:
            assert set(r) == RULING_KEYS
            assert r["frames_source"] in ("ruling", "model", "window")
            assert (r["decided_by"] is not None) == (r["verdict"] == "breach")
            assert (r["lacks"] is not None) == (r["verdict"] == "unable_to_rule")
            assert r["words"] is None  # no words side file in demo/record yet
    # the breach names its own frames: t_s = start_s + n / 24, three at most
    b = json.loads((out / "clips" / "blind_corner_no_vest_07.json").read_text(encoding="utf-8"))
    hv = next(r for r in b["rulings"] if r["rule"] == "hi_vis_in_truck_zone")
    assert hv["frames_source"] == "ruling"
    assert [f["n"] for f in hv["frames"]] == [76, 100, 112]
    assert hv["frames"][0]["t_s"] == round(76 / 24, 3)
    assert "100%" in hv["decided_by"]
    clear = next(r for r in b["rulings"] if r["rule"] == "spotter_when_reversing")
    assert clear["frames_source"] == "window"
    assert [f["n"] for f in clear["frames"]] == [12, 60, 108]


def test_real_footage_numbers_on_their_lines(tmp_path):
    out = tmp_path / "data"
    bundle.build_bundle(_sources(tmp_path), out)
    n = json.loads((out / "index.json").read_text(encoding="utf-8"))["numbers"]
    assert n["real_camera_line"] == {"text": "the line is 1.5 m", "readme_line": 316}
    assert n["real_floor_unable"]["readme_line"] == 317
    assert n["real_floor_unable"]["text"].startswith("every rule that reads the truck's floor")
    assert n["real_floor_unable"]["text"].endswith("is unable to rule")
    assert n["real_hi_vis"] == {
        "text": "the hi-vis rule reads the torso, not the floor, and is still ruled",
        "readme_line": 317,
    }
    # the camera-height sentence moved one line down fails the build
    lines = README.read_text(encoding="utf-8").splitlines()
    lines.insert(315, "")
    moved = tmp_path / "README.md"
    moved.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="line 316"):
        bundle.build_bundle(_sources(tmp_path), out, readme=moved)


def test_byte_identical_twice(tmp_path):
    src = _sources(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    sa, sb = bundle.build_bundle(src, a), bundle.build_bundle(src, b)
    assert sa == sb
    assert _files(a) == _files(b)
    assert bundle.build_bundle(src, a) == sa  # a rebuild over its own output too
    assert sa == bundle.bundle_sha(_files(a))


def test_no_host_path_in_any_file(tmp_path):
    out = tmp_path / "data"
    bundle.build_bundle(_sources(tmp_path), out)
    host = _host_paths(SHIPPED) | {str(SHIPPED), SHIPPED.as_posix(), str(tmp_path)}
    assert host
    for name, b in _files(out).items():
        text = b.decode("ascii")
        for h in host:
            assert h not in text, (name, h)
        assert ".mp4" not in text, name
        assert not re.search(r"[A-Za-z]:[\\/]", text), name


def test_a_number_moved_off_its_line_fails(tmp_path):
    lines = README.read_text(encoding="utf-8").splitlines()
    lines.insert(270, "A new line pushes the scoreboard down by one.")
    moved = tmp_path / "README.md"
    moved.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="line 275"):
        bundle.build_bundle(_sources(tmp_path), tmp_path / "data", readme=moved)
    with pytest.raises(bundle.BundleError):
        bundle.readme_number("one\ntwo 3 of 4\n", 1, r"(\d+ of \d+)")
    assert bundle.readme_number("one\ntwo 3 of 4\n", 2, r"(\d+ of \d+)") == "3 of 4"


def test_graded_hash_with_readme_line_zero_fails(tmp_path):
    graded = {"preds": str(SHIPPED / "preds.jsonl"), "set_sha256": SHIPPED_SHA, "readme_line": 0}
    src = _sources(tmp_path)
    s = json.loads(src.read_text(encoding="utf-8"))
    s["roots"]["graded"] = graded
    src.write_text(json.dumps(s), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="readme_line 0"):
        bundle.build_bundle(src, tmp_path / "data")
    # a null line is refused the same way, never a TypeError
    s["roots"]["graded"]["readme_line"] = None
    src.write_text(json.dumps(s), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="readme_line 0"):
        bundle.build_bundle(src, tmp_path / "data")
    # a hash named on a line that does not hold it fails too
    s["roots"]["graded"]["readme_line"] = 275
    src.write_text(json.dumps(s), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="line 275"):
        bundle.build_bundle(src, tmp_path / "data")


def _copy_record(tmp: Path, name: str) -> Path:
    d = tmp / name
    d.mkdir()
    shutil.copy(SHIPPED / "preds.jsonl", d / "preds.jsonl")
    shutil.copytree(SHIPPED / "entries", d / "entries")
    return d


def test_no_clip_id_twice(tmp_path):
    real = _copy_record(tmp_path, "real")  # a root that holds the featured ids again
    src = _sources(tmp_path)
    s = json.loads(src.read_text(encoding="utf-8"))
    s["roots"]["real"] = {"preds": str(real / "preds.jsonl")}
    src.write_text(json.dumps(s), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="twice"):
        bundle.build_bundle(src, tmp_path / "data")


def test_the_shipped_root_must_hold_the_featured_three(tmp_path):
    d = _copy_record(tmp_path, "shipped")
    lines = (d / "preds.jsonl").read_text(encoding="utf-8").splitlines()
    (d / "preds.jsonl").write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    src = _sources(tmp_path)
    s = json.loads(src.read_text(encoding="utf-8"))
    s["roots"]["shipped"]["preds"] = str(d / "preds.jsonl")
    src.write_text(json.dumps(s), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="features"):
        bundle.build_bundle(src, tmp_path / "data")


def test_frames_follow_the_manifest(tmp_path):
    man = tmp_path / "frames.json"
    rows = [
        {"file": "blind_corner_no_vest_07/76.jpg", "clip": "blind_corner_no_vest_07", "frame": 76},
        {
            "file": "blind_corner_no_vest_07/poster.jpg",
            "clip": "blind_corner_no_vest_07",
            "frame": "poster",
        },
    ]
    for r in rows:
        r["sha256"] = "0" * 64
    man.write_text(json.dumps(rows), encoding="utf-8")
    out = tmp_path / "data"
    bundle.build_bundle(_sources(tmp_path, frames={"manifest": str(man)}), out)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    posters = {c["id"]: c["poster"] for c in index["clips"]}
    assert posters["blind_corner_no_vest_07"] == "frames/blind_corner_no_vest_07/poster.jpg"
    assert posters["spotter_ahead_01"] is None
    b = json.loads((out / "clips" / "blind_corner_no_vest_07.json").read_text(encoding="utf-8"))
    hv = next(r for r in b["rulings"] if r["rule"] == "hi_vis_in_truck_zone")
    assert hv["frames"] == [{"n": 76, "t_s": 3.167, "src": "frames/blind_corner_no_vest_07/76.jpg"}]
    # a manifest row that is a host path is refused
    man.write_text(
        json.dumps([{"file": "C:/x/76.jpg", "clip": "a", "frame": 76, "sha256": "0" * 64}]),
        encoding="utf-8",
    )
    with pytest.raises(bundle.BundleError, match="path"):
        bundle.build_bundle(_sources(tmp_path, frames={"manifest": str(man)}), out)


def test_words_beside_their_own_ruling_and_linted(tmp_path):
    d = _copy_record(tmp_path, "shipped")
    preds = [json.loads(x) for x in (d / "preds.jsonl").read_text(encoding="utf-8").splitlines()]
    p0 = preds[0]  # blind_corner_no_vest_07
    rl = p0["rulings"]
    words = {
        "entry": p0["entry"],
        "id": p0["id"],
        "record": p0["record"],
        "rulings": [
            {
                "rule": rl[0]["rule"],
                "verdict": rl[0]["verdict"],
                "model_read": "breach",
                "note": "A worker on foot walks near the truck; Hi-vis in the truck zone.",
            },
            {
                "rule": rl[1]["rule"],
                "verdict": "breach",  # not the ruling's verdict: dropped
                "note": "A note written for another ruling of Spotter when reversing here.",
            },
            {
                "rule": rl[2]["rule"],
                "verdict": rl[2]["verdict"],  # the lint cuts it
                "note": "A collision between the truck and a person near Pedestrian separation.",
            },
        ],
    }
    (d / "preds.words.jsonl").write_text(json.dumps(words) + "\n", encoding="utf-8")
    src = _sources(tmp_path)
    s = json.loads(src.read_text(encoding="utf-8"))
    s["roots"]["shipped"]["preds"] = str(d / "preds.jsonl")
    src.write_text(json.dumps(s), encoding="utf-8")
    out = tmp_path / "data"
    bundle.build_bundle(src, out)
    b = json.loads((out / "clips" / "blind_corner_no_vest_07.json").read_text(encoding="utf-8"))
    by = {r["rule"]: r["words"] for r in b["rulings"]}
    w0 = by["hi_vis_in_truck_zone"]
    assert w0["note"]["model"] == "Muse Wonder 1.0" and w0["note"]["where"] == "Meta Model API"
    assert w0["reads"] == {
        "model": "Muse Spark Open",
        "where": "Baseten",
        "runs": 3,
        "agreed": "breach",
    }
    assert by["spotter_when_reversing"] is None
    assert by["pedestrian_separation"] is None
    assert "collision" not in (out / "clips" / "blind_corner_no_vest_07.json").read_text()


def test_cli_bundle_subcommand(tmp_path, capsys):
    out = tmp_path / "data"
    rc = cli.main(["bundle", "--sources", str(_sources(tmp_path)), "--out", str(out)])
    assert rc == 0
    assert (out / "index.json").is_file()
    assert "sha256" in capsys.readouterr().out


# ---------------------------------------------------------------- this machine only


def _private_sources(tmp: Path) -> Path:
    """The real sources with the graded hash's README line named, so everything before that check
    is exercised (the line itself is Task 2.2's)."""
    s = json.loads(SOURCES.read_text(encoding="utf-8"))
    sha = s["roots"]["graded"]["set_sha256"]
    readme = tmp / "README.md"
    readme.write_text(
        README.read_text(encoding="utf-8").rstrip("\n") + f"\nGraded set: {sha}\n", encoding="utf-8"
    )
    s["readme"] = str(readme)
    s["roots"]["graded"]["readme_line"] = len(readme.read_text(encoding="utf-8").splitlines())
    for g in ("shipped", "graded", "real"):
        s["roots"][g]["preds"] = str(SITE / s["roots"][g]["preds"])
    s["shift"]["output"]["path"] = str(SITE / Path(s["shift"]["output"]["path"]).relative_to(SITE))
    p = tmp / "sources.json"
    p.write_text(json.dumps(s), encoding="utf-8")
    return p


@pytest.mark.private
@pytest.mark.skipif(not SOURCES.is_file(), reason="data/site/sources.json is not in this tree")
def test_private_real_sources_fail_on_readme_line_zero(tmp_path):
    with pytest.raises(bundle.BundleError, match="readme_line 0"):
        bundle.build_bundle(SOURCES, tmp_path / "data")


@pytest.mark.private
@pytest.mark.skipif(not SOURCES.is_file(), reason="data/site/sources.json is not in this tree")
def test_private_full_bundle(tmp_path):
    src = _private_sources(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    assert bundle.build_bundle(src, a) == bundle.build_bundle(src, b)
    assert _files(a) == _files(b)
    index = json.loads((a / "index.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in index["clips"]]
    assert len(ids) == len(set(ids)) == 28
    groups = [c["group"] for c in index["clips"]]
    assert groups.count("shipped") == 3 and groups.count("graded") == 23
    assert groups.count("real") == 2
    assert {c["kind"] for c in index["clips"] if c["group"] == "real"} == {"real"}
    shift = json.loads((a / "shift.json").read_text(encoding="utf-8"))
    assert len(shift["windows"]) == 48
    assert shift["counts"] == {"breach": 16, "clear": 84, "unable_to_rule": 140}
    host = set()
    for g in ("shipped", "graded", "real"):
        host |= _host_paths(SITE / "record" / g)
    for name, data in _files(a).items():
        text = data.decode("ascii")
        for h in host:
            assert h not in text, (name, h)
        assert not re.search(r"[A-Za-z]:[\\/]", text), name
