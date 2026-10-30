"""Cut masked, hashed JPEG frames from a video stream with ffmpeg, and verify them on replay.

Contract:

- `cut(stream, centre_s, out_dir, masks, span_s=4.0, fps=2, *, error_s=0.0, drop_rules=())`
  writes JPEG frames at `fps` a second over `[centre_s - span_s, centre_s + span_s]` stream
  seconds (17 frames for the defaults). Each frame is one ffmpeg call: a fast seek (`-ss`
  before `-i`, which ffmpeg then decodes forward to the exact frame), `-frames:v 1`, scaled to
  1280x720, then every drawbox filter string in `masks` applied in order (the caller supplies
  them, each a full ffmpeg `drawbox=...` filter), metadata stripped (`-map_metadata -1`,
  bit-exact flags so no encoder tag is written), fixed quality `-q:v 3`. Each file is named by
  its own sha256 plus `.jpg`, so no source name leaks into the frame set. Returns a `Frames`
  list: one `Frame` per kept second, in time order; two seconds that give identical pictures
  share one file.
- Drop rules. Each rule is `{"name": str, "probes": [[x, y], ...], "rgb_min": [r, g, b],
  "rgb_max": [r, g, b]}` on the 1280x720 picture before any mask is drawn (read as rgb24 by
  one more ffmpeg call per second, only when rules are given). A second matches a rule when
  every probe pixel lies inside `[rgb_min, rgb_max]` on each channel (the first matching
  rule names it). A matching second is dropped, and so are its neighbours in time, one each
  side (a cross-fade blends two views), named `next to <rule>`. A dropped second is never
  written to disk. `Frames.dropped` lists them as `Dropped(stream_s, rule)` in time order.
  When every second is dropped, `cut` raises `FramesError` with reason `NO_STANDARD_VIEW`.
- `ffmpeg_version()` is the first line of `ffmpeg -version`; the caller records it.
- `probe_duration(stream)` is the stream's duration in seconds, read with ffprobe.
- `verify(frames_meta, frames_dir)` checks, for replay, that every listed sha256 has a file
  `<sha256>.jpg` in `frames_dir` whose bytes hash to that name.

Refusals (each raises `FramesError`, whose message names the file and the reason): the stream
is missing; ffmpeg or ffprobe is not on PATH; the span widened by `error_s` on each side,
`[centre_s - span_s - error_s, centre_s + span_s + error_s]`, runs outside `[0, duration]`
(reason: `stream does not cover the window`, also exported as `NOT_COVERED`); every second
is dropped (`NO_STANDARD_VIEW`); a malformed drop rule; ffmpeg or ffprobe fails (its stderr
tail is in the message) or writes no picture. `FramesError.reason` holds `NOT_COVERED` or
`NO_STANDARD_VIEW` for those two refusals, else None.

Determinism and its limit: the same call twice on one machine gives the same sha256 list.
JPEG bytes can differ across ffmpeg builds, so the record keeps the hashes of the files this
module produced, and a replay checks those files against their hashes with `verify`; a replay
never re-encodes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "NOT_COVERED",
    "NO_STANDARD_VIEW",
    "Dropped",
    "Frame",
    "Frames",
    "FramesError",
    "check_drop_rules",
    "cut",
    "ffmpeg_version",
    "probe_duration",
    "verify",
]

NOT_COVERED = "stream does not cover the window"
NO_STANDARD_VIEW = "no frame shows the main camera view"
WIDTH = 1280
HEIGHT = 720
QUALITY = 3
_STDERR_TAIL = 800
_RULE_KEYS = {"name", "probes", "rgb_min", "rgb_max"}


class FramesError(ValueError):
    """Frames could not be cut or verified; the message names the file and the reason.

    `reason` is `NOT_COVERED` or `NO_STANDARD_VIEW` for those refusals, else None.
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Frame:
    """One cut frame: its stream second (1 decimal), its sha256 hex and the file it lives in."""

    stream_s: float
    sha256: str
    path: Path


@dataclass(frozen=True)
class Dropped:
    """One second left out by a drop rule: its stream second (1 decimal) and why."""

    stream_s: float
    rule: str


class Frames(list[Frame]):
    """The kept frames, in time order, with `dropped`: the seconds a drop rule left out."""

    def __init__(self, kept: Iterable[Frame] = (), dropped: Iterable[Dropped] = ()) -> None:
        super().__init__(kept)
        self.dropped: tuple[Dropped, ...] = tuple(dropped)


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise FramesError(f"{name}: is not on PATH; install ffmpeg to cut or probe frames.")
    return found


def _tail(text: bytes | str) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text.strip()[-_STDERR_TAIL:]


def ffmpeg_version() -> str:
    """The first line of `ffmpeg -version`."""
    done = subprocess.run([_tool("ffmpeg"), "-version"], capture_output=True, check=False)
    if done.returncode != 0:
        raise FramesError(f"ffmpeg: -version failed ({done.returncode}): {_tail(done.stderr)}")
    lines = done.stdout.decode("utf-8", errors="replace").splitlines()
    if not lines:
        raise FramesError("ffmpeg: -version printed nothing.")
    return lines[0].strip()


def _require_stream(stream: Path) -> None:
    if not stream.is_file():
        raise FramesError(f"{stream}: stream file is missing.")


def probe_duration(stream: str | os.PathLike[str]) -> float:
    """The stream's duration in seconds, from ffprobe's format section."""
    path = Path(stream)
    _require_stream(path)
    done = subprocess.run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        raise FramesError(f"{path}: ffprobe failed ({done.returncode}): {_tail(done.stderr)}")
    text = done.stdout.decode("utf-8", errors="replace").strip()
    try:
        duration = float(text)
    except ValueError as exc:
        raise FramesError(f"{path}: ffprobe gave no duration ({text!r}).") from exc
    if duration != duration or duration <= 0:
        raise FramesError(f"{path}: ffprobe gave no usable duration ({text!r}).")
    return duration


def _filter_chain(masks: Sequence[str]) -> str:
    parts = [f"scale={WIDTH}:{HEIGHT}"]
    for mask in masks:
        if not isinstance(mask, str) or not mask.strip():
            raise FramesError(f"masks: every mask must be a non-empty filter string, not {mask!r}.")
        parts.append(mask.strip())
    return ",".join(parts)


def _one_frame(ffmpeg: str, stream: Path, second: float, chain: str) -> bytes:
    done = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{second:.3f}",
            "-i",
            str(stream),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            chain,
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-q:v",
            str(QUALITY),
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        raise FramesError(
            f"{stream}: ffmpeg failed at {second:.3f} s ({done.returncode}): {_tail(done.stderr)}"
        )
    if not done.stdout:
        raise FramesError(
            f"{stream}: ffmpeg wrote no picture at {second:.3f} s: {_tail(done.stderr)}"
        )
    return done.stdout


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".frame-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cut(
    stream: str | os.PathLike[str],
    centre_s: float,
    out_dir: str | os.PathLike[str],
    masks: Sequence[str],
    span_s: float = 4.0,
    fps: int = 2,
    *,
    error_s: float = 0.0,
    drop_rules: Sequence[Mapping[str, Any]] = (),
) -> Frames:
    """Cut masked JPEG frames at `fps` a second over `[centre_s - span_s, centre_s + span_s]`.

    Seconds a drop rule matches, and their neighbours, are left out (see the module docstring).
    """
    rules = list(drop_rules)
    path = Path(stream)
    _require_stream(path)
    if fps <= 0 or span_s < 0 or error_s < 0:
        raise FramesError(
            f"{path}: fps must be positive and span_s and error_s not negative "
            f"(fps={fps}, span_s={span_s}, error_s={error_s})."
        )
    ffmpeg = _tool("ffmpeg")
    chain = _filter_chain(masks)
    duration = probe_duration(path)
    lo = centre_s - span_s - error_s
    hi = centre_s + span_s + error_s
    if lo < 0 or hi > duration:
        raise FramesError(
            f"{path}: {NOT_COVERED} (needs {lo:.1f} to {hi:.1f} s, the stream runs 0 to "
            f"{duration:.1f} s).",
            reason=NOT_COVERED,
        )
    steps = round(2 * span_s * fps)
    seconds = [centre_s - span_s + k / fps for k in range(steps + 1)]
    why = _drops(ffmpeg, path, seconds, rules)
    if len(why) == len(seconds):
        raise FramesError(
            f"{path}: {NO_STANDARD_VIEW} (all {len(seconds)} seconds from {seconds[0]:.1f} "
            f"to {seconds[-1]:.1f} s matched a drop rule or sat next to one).",
            reason=NO_STANDARD_VIEW,
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    kept: list[Frame] = []
    for index, second in enumerate(seconds):
        if index in why:
            continue
        data = _one_frame(ffmpeg, path, second, chain)
        sha = hashlib.sha256(data).hexdigest()
        target = out / f"{sha}.jpg"
        if not target.is_file() or target.read_bytes() != data:
            _write_atomic(target, data)
        kept.append(Frame(stream_s=round(second, 1), sha256=sha, path=target))
    dropped = [Dropped(stream_s=round(seconds[i], 1), rule=why[i]) for i in sorted(why)]
    return Frames(kept, dropped)


def check_drop_rules(rules: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The drop rules, checked (see the module docstring); a malformed one raises."""
    checked: list[dict[str, Any]] = []
    for n, rule in enumerate(rules):
        where = f"drop rule {n}"
        if not isinstance(rule, Mapping) or set(rule) != _RULE_KEYS:
            raise FramesError(f"{where}: needs exactly the keys {sorted(_RULE_KEYS)}.")
        name = rule["name"]
        if not isinstance(name, str) or not name.strip():
            raise FramesError(f"{where}: name must be a non-empty string.")
        probes = rule["probes"]
        if not isinstance(probes, list) or not probes:
            raise FramesError(f"{where} ({name}): probes must be a non-empty list of [x, y].")
        for probe in probes:
            if (
                not isinstance(probe, list | tuple)
                or len(probe) != 2
                or not all(_whole(v) for v in probe)
                or not (0 <= probe[0] < WIDTH and 0 <= probe[1] < HEIGHT)
            ):
                raise FramesError(
                    f"{where} ({name}): probe {probe!r} is not [x, y] inside {WIDTH}x{HEIGHT}."
                )
        bounds = []
        for key in ("rgb_min", "rgb_max"):
            value = rule[key]
            if (
                not isinstance(value, list | tuple)
                or len(value) != 3
                or not all(_whole(v) and 0 <= v <= 255 for v in value)
            ):
                raise FramesError(f"{where} ({name}): {key} must be three whole numbers 0-255.")
            bounds.append([int(v) for v in value])
        checked.append(
            {
                "name": name,
                "probes": [(int(x), int(y)) for x, y in probes],
                "rgb_min": bounds[0],
                "rgb_max": bounds[1],
            }
        )
    return checked


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _rgb_frame(ffmpeg: str, stream: Path, second: float) -> bytes:
    """The unmasked 1280x720 picture at `second`, as raw rgb24 bytes."""
    done = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{second:.3f}",
            "-i",
            str(stream),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            f"scale={WIDTH}:{HEIGHT}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        raise FramesError(
            f"{stream}: ffmpeg failed reading pixels at {second:.3f} s ({done.returncode}): "
            f"{_tail(done.stderr)}"
        )
    if len(done.stdout) != WIDTH * HEIGHT * 3:
        raise FramesError(
            f"{stream}: ffmpeg gave {len(done.stdout)} pixel bytes at {second:.3f} s, "
            f"not {WIDTH * HEIGHT * 3}."
        )
    return done.stdout


def _matches(pixels: bytes, rule: Mapping[str, Any]) -> bool:
    lo, hi = rule["rgb_min"], rule["rgb_max"]
    for x, y in rule["probes"]:
        at = (y * WIDTH + x) * 3
        if not all(lo[c] <= pixels[at + c] <= hi[c] for c in range(3)):
            return False
    return True


def _drops(
    ffmpeg: str, stream: Path, seconds: Sequence[float], rules: Sequence[Mapping[str, Any]]
) -> dict[int, str]:
    """Index -> why, for every second a rule drops (matched, or next to a match)."""
    checked = check_drop_rules(rules)
    if not checked:
        return {}
    matched: dict[int, str] = {}
    for index, second in enumerate(seconds):
        pixels = _rgb_frame(ffmpeg, stream, second)
        hit = next((r["name"] for r in checked if _matches(pixels, r)), None)
        if hit is not None:
            matched[index] = hit
    why = dict(matched)
    for index in range(len(seconds)):
        if index in why:
            continue
        for side in (index - 1, index + 1):
            if side in matched:
                why[index] = f"next to {matched[side]}"
                break
    return why


def verify(
    frames_meta: Iterable[Mapping[str, object] | Frame], frames_dir: str | os.PathLike[str]
) -> None:
    """Check every listed frame file exists in `frames_dir` and hashes to its own name."""
    folder = Path(frames_dir)
    for item in frames_meta:
        sha = item.sha256 if isinstance(item, Frame) else item.get("sha256")
        if not isinstance(sha, str) or not sha:
            raise FramesError(f"{folder}: a frame entry has no sha256 ({item!r}).")
        target = folder / f"{sha}.jpg"
        if not target.is_file():
            raise FramesError(f"{target}: frame {sha} is missing.")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != sha:
            raise FramesError(f"{target}: frame {sha} has changed (its bytes hash to {actual}).")
