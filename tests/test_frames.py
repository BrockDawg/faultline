"""frames: cut masked, hashed JPEG frames from a synthetic `testsrc` video made at test time."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from faultline import frames
from faultline.frames import NOT_COVERED, Frame, FramesError, cut, probe_duration, verify

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg and ffprobe are not on PATH")

SECRET_TITLE = "SourceTitleMarker"
MASK = "drawbox=x=0:y=0:w=200:h=120:color=black:t=fill"


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg and ffprobe are not on PATH")
    path = tmp_path_factory.mktemp("video") / "source-name-marker.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=10:size=640x360:rate=25",
            "-metadata",
            f"title={SECRET_TITLE}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _gray_pixels(jpg: Path) -> bytes:
    done = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(jpg), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True,
        capture_output=True,
    )
    assert len(done.stdout) == 1280 * 720
    return done.stdout


def _region_max(pixels: bytes, x0: int, y0: int, x1: int, y1: int) -> int:
    return max(max(pixels[y * 1280 + x0 : y * 1280 + x1]) for y in range(y0, y1))


@needs_ffmpeg
def test_seventeen_frames_named_by_their_hash(video: Path, tmp_path: Path) -> None:
    got = cut(video, 5.0, tmp_path / "out", [MASK])
    assert len(got) == 17
    assert [f.stream_s for f in got] == [round(1.0 + k * 0.5, 1) for k in range(17)]
    for f in got:
        assert f.path.name == f"{f.sha256}.jpg"
        assert f.path.parent == tmp_path / "out"
        assert hashlib.sha256(f.path.read_bytes()).hexdigest() == f.sha256
    # testsrc moves every frame, so every second is a distinct picture
    assert len({f.sha256 for f in got}) == 17
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        f"{f.sha256}.jpg" for f in got
    )


@needs_ffmpeg
def test_two_calls_give_equal_hashes(video: Path, tmp_path: Path) -> None:
    a = cut(video, 5.0, tmp_path / "a", [MASK])
    b = cut(video, 5.0, tmp_path / "b", [MASK])
    assert [f.sha256 for f in a] == [f.sha256 for f in b]


@needs_ffmpeg
def test_mask_turns_its_rectangle_black(video: Path, tmp_path: Path) -> None:
    masked = cut(video, 5.0, tmp_path / "m", [MASK], span_s=0.0)
    plain = cut(video, 5.0, tmp_path / "p", [], span_s=0.0)
    assert len(masked) == len(plain) == 1
    m = _gray_pixels(masked[0].path)
    p = _gray_pixels(plain[0].path)
    # inside the box, a margin clear of JPEG ringing at its edge
    assert _region_max(m, 4, 4, 196, 116) < 20
    assert _region_max(p, 4, 4, 196, 116) > 60
    # outside the box the picture is still there
    assert _region_max(m, 600, 300, 900, 500) > 60


@needs_ffmpeg
def test_metadata_and_source_name_stripped(video: Path, tmp_path: Path) -> None:
    got = cut(video, 5.0, tmp_path / "out", [MASK], span_s=0.5)
    for f in got:
        data = f.path.read_bytes()
        assert SECRET_TITLE.encode() not in data
        assert b"source-name-marker" not in data
        assert b"Lavc" not in data
        assert b"Exif" not in data
        assert "source-name-marker" not in f.path.name


@needs_ffmpeg
def test_centre_near_the_end_refuses(video: Path, tmp_path: Path) -> None:
    with pytest.raises(FramesError, match=NOT_COVERED) as err:
        cut(video, 8.0, tmp_path / "out", [MASK])
    assert str(video) in str(err.value)
    assert NOT_COVERED == "stream does not cover the window"
    assert not (tmp_path / "out").exists()


@needs_ffmpeg
def test_error_widens_the_window(video: Path, tmp_path: Path) -> None:
    assert len(cut(video, 5.0, tmp_path / "ok", [], error_s=1.0)) == 17
    with pytest.raises(FramesError, match=NOT_COVERED):
        cut(video, 5.0, tmp_path / "out", [], error_s=2.0)
    with pytest.raises(FramesError, match=NOT_COVERED):
        cut(video, 3.0, tmp_path / "out", [])


def test_missing_stream_refuses(tmp_path: Path) -> None:
    missing = tmp_path / "absent.mp4"
    with pytest.raises(FramesError, match="missing") as err:
        cut(missing, 5.0, tmp_path / "out", [])
    assert str(missing) in str(err.value)


def test_missing_ffmpeg_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stream = tmp_path / "s.mp4"
    stream.write_bytes(b"x")
    monkeypatch.setattr(frames.shutil, "which", lambda name: None)
    with pytest.raises(FramesError, match="not on PATH"):
        cut(stream, 5.0, tmp_path / "out", [])
    with pytest.raises(FramesError, match="ffprobe: is not on PATH"):
        probe_duration(stream)


@needs_ffmpeg
def test_ffmpeg_failure_carries_its_stderr(video: Path, tmp_path: Path) -> None:
    with pytest.raises(FramesError, match="ffmpeg failed") as err:
        cut(video, 5.0, tmp_path / "out", ["drawbox=nosuchoption=1"], span_s=0.0)
    assert "nosuchoption" in str(err.value) or "Option" in str(err.value)


@needs_ffmpeg
def test_broken_stream_refuses_with_ffprobe_stderr(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(FramesError, match="ffprobe failed"):
        probe_duration(bad)


@needs_ffmpeg
def test_probe_duration(video: Path) -> None:
    assert probe_duration(video) == pytest.approx(10.0, abs=0.1)


@needs_ffmpeg
def test_ffmpeg_version_is_one_line() -> None:
    line = frames.ffmpeg_version()
    assert line.startswith("ffmpeg version")
    assert "\n" not in line


@needs_ffmpeg
def test_verify_passes_then_catches_change_and_loss(video: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    got = cut(video, 5.0, out, [MASK], span_s=1.0)
    meta = [{"stream_s": f.stream_s, "sha256": f.sha256} for f in got]
    verify(meta, out)
    verify(got, out)

    changed = got[1]
    changed.path.write_bytes(changed.path.read_bytes() + b"\x00")
    with pytest.raises(FramesError, match=f"{changed.sha256} has changed"):
        verify(meta, out)

    changed.path.unlink()
    with pytest.raises(FramesError, match=f"{changed.sha256} is missing"):
        verify(meta, out)


def test_verify_refuses_an_entry_without_a_hash(tmp_path: Path) -> None:
    with pytest.raises(FramesError, match="no sha256"):
        verify([{"stream_s": 1.0}], tmp_path)


def test_frame_is_frozen(tmp_path: Path) -> None:
    f = Frame(stream_s=1.0, sha256="a" * 64, path=tmp_path / "x.jpg")
    with pytest.raises(AttributeError):
        f.stream_s = 2.0  # type: ignore[misc]


# ------------------------------------------------------------------ drop rules (other layouts)

BAR_X = 290
ORANGE = "0xE04010"
PIP = {
    "name": "picture-in-picture",
    "probes": [[BAR_X, 100], [BAR_X, 250], [BAR_X, 400]],
    "rgb_min": [180, 0, 0],
    "rgb_max": [255, 80, 40],
}
STACKED = {**PIP, "name": "stacked", "probes": [[304, 100], [304, 200], [304, 300]]}


def _bar_video(path: Path, enable: str | None) -> Path:
    """A 10 s testsrc at 1280x720 with an orange vertical bar at x=290 while `enable` holds."""
    vf = "null"
    if enable is not None:
        vf = f"drawbox=x={BAR_X - 10}:y=0:w=20:h=720:color={ORANGE}:t=fill:enable='{enable}'"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc=duration=10:size=1280x720:rate=10", "-vf", vf, "-pix_fmt", "yuv420p",
         str(path)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def bar_videos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg and ffprobe are not on PATH")
    base = tmp_path_factory.mktemp("bars")
    return {
        "one_second": _bar_video(base / "one.mp4", "between(t,3.95,5.05)"),
        "none": _bar_video(base / "none.mp4", None),
        "always": _bar_video(base / "always.mp4", "gte(t,0)"),
    }


@needs_ffmpeg
def test_a_layout_second_and_its_neighbours_are_dropped(
    bar_videos: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    got = cut(bar_videos["one_second"], 5.0, out, [MASK], drop_rules=[STACKED, PIP])
    assert isinstance(got, frames.Frames)
    assert [(d.stream_s, d.rule) for d in got.dropped] == [
        (3.5, "next to picture-in-picture"),
        (4.0, "picture-in-picture"),
        (4.5, "picture-in-picture"),
        (5.0, "picture-in-picture"),
        (5.5, "next to picture-in-picture"),
    ]
    kept = [f.stream_s for f in got]
    assert kept == [1.0, 1.5, 2.0, 2.5, 3.0, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]
    # A dropped second is never written; the kept ones are, and they verify.
    assert sorted(p.name for p in out.iterdir()) == sorted({f"{f.sha256}.jpg" for f in got})
    verify(got, out)
    again = cut(bar_videos["one_second"], 5.0, tmp_path / "again", [MASK], drop_rules=[PIP])
    assert [f.sha256 for f in again] == [f.sha256 for f in got]


@needs_ffmpeg
def test_no_layout_drops_nothing(bar_videos: dict[str, Path], tmp_path: Path) -> None:
    got = cut(bar_videos["none"], 5.0, tmp_path / "out", [MASK], drop_rules=[STACKED, PIP])
    assert len(got) == 17 and got.dropped == ()
    plain = cut(bar_videos["none"], 5.0, tmp_path / "plain", [MASK])
    assert [f.sha256 for f in got] == [f.sha256 for f in plain]


@needs_ffmpeg
def test_every_second_dropped_refuses(bar_videos: dict[str, Path], tmp_path: Path) -> None:
    with pytest.raises(FramesError, match=frames.NO_STANDARD_VIEW) as err:
        cut(bar_videos["always"], 5.0, tmp_path / "out", [MASK], drop_rules=[PIP])
    assert err.value.reason == frames.NO_STANDARD_VIEW
    assert frames.NO_STANDARD_VIEW == "no frame shows the main camera view"
    assert not (tmp_path / "out").exists()


@needs_ffmpeg
def test_not_covered_carries_its_reason(video: Path, tmp_path: Path) -> None:
    with pytest.raises(FramesError) as err:
        cut(video, 8.0, tmp_path / "out", [MASK])
    assert err.value.reason == NOT_COVERED


@pytest.mark.parametrize(
    "bad",
    [
        {**PIP, "extra": 1},
        {**PIP, "name": ""},
        {**PIP, "probes": []},
        {**PIP, "probes": [[1280, 0]]},
        {**PIP, "probes": [[1.5, 2]]},
        {**PIP, "rgb_min": [0, 0]},
        {**PIP, "rgb_max": [0, 0, 256]},
    ],
)
@needs_ffmpeg
def test_a_malformed_drop_rule_is_refused(
    bar_videos: dict[str, Path], tmp_path: Path, bad: dict
) -> None:
    with pytest.raises(FramesError, match="drop rule 0"):
        cut(bar_videos["none"], 5.0, tmp_path / "out", [MASK], drop_rules=[bad])
