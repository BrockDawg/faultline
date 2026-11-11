"""scripts/site_clips.py: the window the judge read comes out at its length, with no audio, the
manifest hashes match, a rerun is byte-identical, an unproven window is skipped, and a length the
record cannot give stops the run."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import site_clips  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is absent",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _clip(path: Path) -> Path:
    """A 3-second 24 fps test clip with a sine audio track (so stripping it is proven)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=3",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path


class Shift:
    """A tiny shift: a record (windows.jsonl + entries), sources.json, and a bundle."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.record = root / "shift-record"
        (self.record / "entries").mkdir(parents=True)
        self.bundle = root / "site" / "data"
        self.bundle.mkdir(parents=True)
        self.out = self.bundle / "video"
        self.sources = root / "sources.json"
        self.sources.write_text(
            json.dumps({"shift": {"output": {"path": str(self.record)}}}), encoding="utf-8"
        )
        (self.bundle / "index.json").write_text(
            json.dumps({"clips": [{"id": "real_aisle_01", "group": "real", "kind": "real"}]}),
            encoding="utf-8",
        )
        self.rows: list[dict] = []
        self.windows: list[dict] = []

    def add(
        self,
        wid: str,
        clip: Path,
        start: float,
        end: float,
        window_s: float | None,
        record_clip: Path | None = None,
    ) -> None:
        sha = _sha(clip)
        entry = f"fl-{wid}"
        self.rows.append(
            {
                "window": wid,
                "clip": (record_clip or clip).as_posix(),
                "clip_sha256": sha,
                "entry": entry,
                "record": f"rec-{wid}",
                "start_s": start,
                "end_s": end,
            }
        )
        gates = {} if window_s is None else {"window_s": window_s, "frames": 12}
        doc = {
            "entry": entry,
            "clip_sha256": sha,
            "item": {"id": wid, "start_s": start, "end_s": end},
            "gates": gates,
        }
        (self.record / "entries" / f"{entry}.json").write_text(json.dumps(doc), encoding="utf-8")
        self.windows.append(
            {"window": wid, "clip": clip.stem, "entry": entry, "record": f"rec-{wid}"}
        )
        self.write()

    def write(self) -> None:
        (self.record / "windows.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8"
        )
        (self.bundle / "shift.json").write_text(
            json.dumps({"schema": 1, "windows": self.windows}), encoding="utf-8"
        )

    def build(self) -> dict:
        return site_clips.build(self.sources, self.out, workers=2)


@pytest.fixture
def shift(tmp_path: Path) -> Shift:
    return Shift(tmp_path)


def _probe(p: Path) -> dict:
    return site_clips.ffprobe(p)


def test_the_window_comes_out_at_its_length_with_no_audio(shift: Shift, tmp_path: Path) -> None:
    clip = _clip(tmp_path / "corpus" / "synthetic" / "pairs" / "dock_07.mp4")
    assert "audio" in [s["codec_type"] for s in _probe(clip)["streams"]]
    shift.add("w01-dock_07", clip, 0.5, 2.5, 2.0)
    res = shift.build()
    assert res["videos"] == 1 and res["skipped"] == []
    mp4 = shift.out / "w01-dock_07.mp4"
    probe = _probe(mp4)
    assert [s["codec_type"] for s in probe["streams"]] == ["video"]
    assert abs(float(probe["format"]["duration"]) - 2.0) <= 1 / 24 + 1e-3
    assert probe["streams"][0]["width"] == 640
    manifest = json.loads((shift.out / "videos.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    (v,) = manifest["videos"]
    assert v == {
        "audio": False,
        "bytes": mp4.stat().st_size,
        "clip": "dock_07",
        "duration_s": 2.0,
        "file": "video/w01-dock_07.mp4",
        "fps": 24.0,
        "height": 480,
        "sha256": _sha(mp4),
        "start_s": 0.5,
        "width": 640,
        "window": "w01-dock_07",
    }


def test_the_start_is_the_records_start(shift: Shift, tmp_path: Path) -> None:
    # testsrc draws a running clock: the first frame of a window from 1.0 s differs from one at 0
    clip = _clip(tmp_path / "corpus" / "synthetic" / "a" / "dock_07.mp4")
    shift.add("w01-dock_07", clip, 0.0, 1.0, 1.0)
    shift.add("w02-dock_07", clip, 1.0, 2.0, 1.0)
    shift.build()
    a, b = _sha(shift.out / "w01-dock_07.mp4"), _sha(shift.out / "w02-dock_07.mp4")
    assert a != b


def test_a_rerun_is_byte_identical(shift: Shift, tmp_path: Path) -> None:
    clip = _clip(tmp_path / "corpus" / "synthetic" / "pairs" / "dock_07.mp4")
    shift.add("w01-dock_07", clip, 0.0, 3.0, 3.0)
    shift.build()
    first = {p.name: _sha(p) for p in sorted(shift.out.iterdir())}
    shift.build()
    assert {p.name: _sha(p) for p in sorted(shift.out.iterdir())} == first
    assert set(first) == {"w01-dock_07.mp4", "videos.json"}


def test_an_unproven_or_real_window_is_skipped(shift: Shift, tmp_path: Path) -> None:
    good = _clip(tmp_path / "corpus" / "synthetic" / "pairs" / "dock_07.mp4")
    real = _clip(tmp_path / "corpus" / "real" / "aisle" / "real_aisle_01.mp4")
    other = _clip(tmp_path / "corpus" / "kept" / "dock_09.mp4")
    shift.add("w01-dock_07", good, 0.0, 2.0, 2.0)
    shift.add("w02-real_aisle_01", real, 0.0, 2.0, 2.0)
    shift.add("w03-dock_09", other, 0.0, 2.0, 2.0)  # not from a synthetic folder
    shift.windows[2]["record"] = "rec-other"  # nor does the record hash match
    shift.write()
    res = shift.build()
    assert res["videos"] == 1
    assert sorted(s["window"] for s in res["skipped"]) == ["w02-real_aisle_01", "w03-dock_09"]
    assert sorted(p.name for p in shift.out.glob("*.mp4")) == ["w01-dock_07.mp4"]


def test_a_real_clip_named_in_a_synthetic_folder_is_still_skipped(
    shift: Shift, tmp_path: Path
) -> None:
    clip = _clip(tmp_path / "corpus" / "synthetic" / "real_aisle_01.mp4")
    shift.add("w01-real_aisle_01", clip, 0.0, 2.0, 2.0)
    res = shift.build()
    assert res["videos"] == 0
    assert res["skipped"][0]["why"] == "its clip is in the real group"


@pytest.mark.parametrize("window_s", [None, 4.0, 0.0])
def test_a_length_the_record_cannot_give_stops_the_run(
    shift: Shift, tmp_path: Path, window_s: float | None
) -> None:
    # None: no window_s; 4.0: longer than the 3 s clip allows; 0.0: nothing read
    clip = _clip(tmp_path / "corpus" / "synthetic" / "pairs" / "dock_07.mp4")
    shift.add("w01-dock_07", clip, 0.0, 5.0, window_s)
    with pytest.raises(site_clips.ClipsError):
        shift.build()
    assert not shift.out.exists()
    assert site_clips.main(["--sources", str(shift.sources), "--out", str(shift.out)]) == 2


def test_changed_clip_bytes_stop_the_run(shift: Shift, tmp_path: Path) -> None:
    clip = _clip(tmp_path / "corpus" / "synthetic" / "pairs" / "dock_07.mp4")
    shift.add("w01-dock_07", clip, 0.0, 2.0, 2.0)
    clip.write_bytes(clip.read_bytes() + b"\0")
    with pytest.raises(site_clips.ClipsError, match="bytes changed"):
        shift.build()


def test_the_window_length_from_a_short_clip_is_the_records(shift: Shift, tmp_path: Path) -> None:
    # the window asks for 5 s, the clip holds 3: the judge read 3 s and the record says so
    clip = _clip(tmp_path / "corpus" / "synthetic" / "pairs" / "dock_07.mp4")
    shift.add("w01-dock_07", clip, 0.0, 5.0, 3.0)
    shift.build()
    (v,) = json.loads((shift.out / "videos.json").read_text(encoding="utf-8"))["videos"]
    assert v["duration_s"] == 3.0
    got = float(_probe(shift.out / "w01-dock_07.mp4")["format"]["duration"])
    assert abs(got - 3.0) <= 1 / 24 + 1e-3
