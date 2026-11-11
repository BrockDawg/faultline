"""scripts/site_frames.py: the right frames, matching manifest hashes, real frames blurred and
unchecked, frames with no person box dropped, and a byte-identical rerun."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import site_frames  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is absent",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _clip(path: Path, src: str) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            src,
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path


def _luma(jpg: Path) -> float:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(jpg),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return float(np.frombuffer(raw, dtype=np.uint8).mean())


def _ramp(n: int) -> float:
    """The full-range grey a JPEG shows for ramp frame n (video range 40 + 4n)."""
    return (40 + 4 * n - 16) * 255 / 219


def _root(base: Path, name: str, clips: list[tuple[str, Path, list[int], float]]) -> Path:
    """A record root: preds.jsonl plus one entry per clip; each clip has one ruling."""
    rec = base / "record" / name
    (rec / "entries").mkdir(parents=True)
    lines = []
    for k, (cid, clip, frames, start) in enumerate(clips):
        entry = f"fl-{name}{k}"
        item = {"clip": str(clip), "id": cid, "start_s": start, "end_s": 2.0}
        (rec / "entries" / f"{entry}.json").write_text(
            json.dumps({"clip_sha256": _sha(clip), "entry": entry, "item": item}), "utf-8"
        )
        rulings = [
            {
                "rule": "r1",
                "verdict": "breach",
                "frames": frames,
                "evidence": "e",
                "missing_fact": None,
            }
        ]
        lines.append(json.dumps({"entry": entry, "id": cid, "record": "x", "rulings": rulings}))
    (rec / "preds.jsonl").write_text("\n".join(lines) + "\n", "utf-8")
    return rec


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("site")
    clips = base / "clips"
    clips.mkdir()
    # luma = 40 + 4 * frame number (video range), so each cut frame names itself
    ramp = _clip(
        clips / "ramp.mp4", "nullsrc=s=64x48:r=24:d=2,geq=lum='40+4*N':cb=128:cr=128,format=yuv420p"
    )
    test = _clip(clips / "test.mp4", "testsrc=duration=2:size=320x240:rate=24")
    real = _clip(clips / "real.mp4", "testsrc=duration=2:size=1920x1080:rate=24")
    _root(base, "shipped", [("ramp", ramp, [3, 9, 20, 30], 0.0), ("ramp_late", ramp, [], 0.5)])
    # "ramp" is featured: its graded copy (frame 40) must be skipped, the shipped one wins
    _root(base, "graded", [("test", test, [], 0.0), ("ramp", ramp, [40], 0.0)])
    real_rec = _root(base, "real", [("real", real, [4, 8], 0.0)])
    # person boxes on mask frames 2..4 and 30 (12 fps): frame 4 -> 2, frame 8 -> 4,
    # window frames 12 -> 6 (box 4 within 2), 60 -> 30, 108 is past the clip
    cd = real_rec / "clips" / _sha(real)
    (cd / "masks").mkdir(parents=True)
    reply = b"person boxes"
    (cd / "person_track.txt").write_bytes(reply)
    np.savez(
        cd / "masks" / f"{hashlib.sha256(reply).hexdigest()}.npz",
        **{f"b_{m}_0": np.array([400, 100, 700, 600]) for m in (2, 3, 4, 30)},
    )
    # the 'test' clip's model frames come from a stored note
    gd = base / "record" / "graded"
    note = gd / "clips" / _sha(test) / "wonder" / "0.000_2.000" / "note.json"
    note.parent.mkdir(parents=True)
    note.write_text(json.dumps({"frames": [5, 10, 15, 20]}), "utf-8")
    sources = {
        "schema": 1,
        "roots": {
            "shipped": {"preds": "record/shipped/preds.jsonl"},
            "graded": {"preds": "record/graded/preds.jsonl", "clip_mp4s": {"d": str(clips)}},
            "real": {"preds": "record/real/preds.jsonl"},
        },
    }
    sp = base / "sources.json"
    sp.write_text(json.dumps(sources), "utf-8")
    # shift output: one window over the ramp clip, poster at its middle frame
    sh = base / "shift"
    sh.mkdir()
    (sh / "windows.jsonl").write_text(
        json.dumps(
            {
                "window": "w01-ramp",
                "clip": str(ramp),
                "clip_sha256": _sha(ramp),
                "start_s": 0.0,
                "end_s": 2.0,
            }
        )
        + "\n",
        "utf-8",
    )
    sources["shift"] = {"output": {"path": str(sh)}}
    sp.write_text(json.dumps(sources), "utf-8")
    out = base / "data" / "frames"
    res = site_frames.build(sp, out, workers=2)
    return {"base": base, "sources": sp, "out": out, "res": res}


def test_ruling_frames_are_the_right_frames(world):
    out = world["out"]
    rul = json.loads((out / "frames.json").read_text("utf-8"))["rulings"]
    # four named frames -> first, middle, last
    assert rul["shipped/ramp"]["r1"] == {
        "frames": [3, 20, 30],
        "frames_source": "ruling",
        "dropped": [],
    }
    for n in (3, 20, 30):
        assert abs(_luma(out / "ramp" / f"{n}.jpg") - _ramp(n)) < 3, n
    # a window starting at 0.5 s: frame 12 there is clip frame 24
    assert rul["shipped/ramp_late"]["r1"]["frames_source"] == "window"
    assert rul["shipped/ramp_late"]["r1"]["frames"] == [12, 35]  # 60 and 108 clamp to the last
    assert abs(_luma(out / "ramp_late" / "12.jpg") - _ramp(24)) < 3
    assert abs(_luma(out / "ramp_late" / "35.jpg") - _ramp(47)) < 3


def test_model_frames_then_window(world):
    rul = json.loads((world["out"] / "frames.json").read_text("utf-8"))["rulings"]
    assert rul["graded/test"]["r1"] == {
        "frames": [5, 15, 20],
        "frames_source": "model",
        "dropped": [],
    }


def test_manifest_hashes_match_and_cover_every_jpeg(world):
    out = world["out"]
    man = json.loads((out / "frames.json").read_text("utf-8"))
    files = {f["file"] for f in man["frames"]}
    on_disk = {p.relative_to(out.parent).as_posix() for p in out.rglob("*.jpg")}
    assert files == on_disk
    for f in man["frames"]:
        assert _sha(out.parent / f["file"]) == f["sha256"]
        assert ":" not in f["file"] and not f["file"].startswith("/")
    posters = {"frames/ramp/poster.jpg", "frames/test/poster.jpg", "frames/real/poster.jpg"}
    assert posters | {"frames/w01-ramp/poster.jpg"} <= files
    for f in man["frames"]:
        if f["file"].endswith("poster.jpg"):
            assert f["frame"] == "poster" and isinstance(f["at_frame"], int)
        else:
            assert f["file"] == f"frames/{f['clip']}/{f['frame']}.jpg"
    shift = next(f for f in man["frames"] if f["clip"] == "w01-ramp")
    assert shift["at_frame"] == 24 and abs(_luma(out / "w01-ramp" / "poster.jpg") - _ramp(24)) < 3
    for f in man["frames"]:
        assert (
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=width",
                    "-of",
                    "csv=p=0",
                    str(out.parent / f["file"]),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            == "640"
        )


def test_real_frames_blurred_unchecked_and_boxless_dropped(world):
    out = world["out"]
    bl = json.loads((out / "blurred.json").read_text("utf-8"))
    man = json.loads((out / "frames.json").read_text("utf-8"))
    real_files = {f["file"] for f in man["frames"] if f["kind"] == "real"}
    assert real_files == {f["file"] for f in bl["frames"]}
    assert real_files == {"frames/real/4.jpg", "frames/real/8.jpg", "frames/real/poster.jpg"}
    assert all(f["checked"] is False for f in bl["frames"])
    assert all(f["blurred"] for f in man["frames"] if f["kind"] == "real")
    # frame 4 -> mask 2: region widened 15%, from 5% above the top to 60% of the height
    f4 = next(f for f in bl["frames"] if f["file"] == "frames/real/4.jpg")
    assert f4["box_frame"] == 2 and f4["regions"] == [[355, 75, 745, 400]]
    # the poster is the window middle (24 -> mask 12) moved to the nearest boxed frame (12)
    assert next(f for f in man["frames"] if f["file"] == "frames/real/poster.jpg")["at_frame"] == 12
    # the blurred region is flat where testsrc is busy
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(out / "real/4.jpg"),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(360, 640)
    inner = img[50:190, 200:350].astype(float)  # inside the region, scaled by 0.5
    assert np.abs(np.diff(inner, axis=1)).mean() < 2.0
    # the real ruling had no own frames past 4 and 8, so no window frame was needed
    assert man["rulings"]["real/real"]["r1"]["frames"] == [4, 8]


def test_window_frame_without_box_is_dropped(tmp_path, world):
    # the same real root with no named frames: 12 is covered (mask 6, box 4), 60 -> 47
    # (clamped) has no box within 2, so it is never written
    base = world["base"]
    rec = base / "record" / "real"
    line = json.loads((rec / "preds.jsonl").read_text("utf-8"))
    line["rulings"][0]["frames"] = []
    (tmp_path / "record" / "real").mkdir(parents=True)
    shutil.copytree(rec / "entries", tmp_path / "record" / "real" / "entries")
    shutil.copytree(rec / "clips", tmp_path / "record" / "real" / "clips")
    (tmp_path / "record" / "real" / "preds.jsonl").write_text(json.dumps(line) + "\n", "utf-8")
    sp = tmp_path / "sources.json"
    sp.write_text(json.dumps({"roots": {"real": {"preds": "record/real/preds.jsonl"}}}), "utf-8")
    out = tmp_path / "out"
    site_frames.build(sp, out, workers=1)
    rul = json.loads((out / "frames.json").read_text("utf-8"))["rulings"]["real/real"]["r1"]
    assert rul == {"frames": [12], "frames_source": "window", "dropped": [47]}
    assert not (out / "real" / "47.jpg").exists()
    bl = json.loads((out / "blurred.json").read_text("utf-8"))
    assert [d["frame"] for d in bl["dropped"]] == [47]


def test_rerun_is_byte_identical(world, tmp_path):
    out = world["out"]
    before = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    (out / "stale").mkdir()
    (out / "stale" / "old.jpg").write_bytes(b"x")
    site_frames.build(world["sources"], out, workers=3)
    after = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert before == after


def test_cut_refuses_a_real_frame_without_region(tmp_path, world):
    clip = world["base"] / "clips" / "real.mp4"
    with pytest.raises(ValueError):
        site_frames.cut(clip, 0.0, 24.0, tmp_path / "x.jpg", [])
    assert not (tmp_path / "x.jpg").exists()


def test_featured_clip_comes_from_shipped_only(world):
    out = world["out"]
    man = json.loads((out / "frames.json").read_text("utf-8"))
    assert "graded/ramp" not in man["rulings"]
    assert "shipped/ramp" in man["rulings"] and "graded/test" in man["rulings"]
    assert not (out / "ramp" / "40.jpg").exists()
    assert all(f["frame"] != 40 for f in man["frames"] if f["clip"] == "ramp")
