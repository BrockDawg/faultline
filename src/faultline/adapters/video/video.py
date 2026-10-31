"""ffmpeg in, numpy out. Decoding is deterministic for the same bytes, so a frame hash in the record
pins it.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import numpy as np

W, H = 1280, 720
FPS = 12  # the measuring rate: SAM's encode and every per-frame field share it
SRC_FPS = 24  # the synthetic clips' native rate; a ruling's frame indexes are given at this rate


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _run(cmd: list[str], timeout: int = 600) -> bytes:
    """Run ffmpeg; a command that writes to stdout ('-' last) writes to a temporary file instead and
    the file is read back (the same bytes). On a machine short of memory the pipe's reader thread
    died with MemoryError and the decode hung until the timeout; a file has no reader thread."""
    if not cmd or cmd[-1] != "-":
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=True).stdout
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out.bin")
        subprocess.run(
            [*cmd[:-1], "-y", out],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=True,
        )
        return Path(out).read_bytes()


def probe(path: str | Path) -> dict:
    out = (
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,nb_frames,duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .split(",")
    )
    try:
        num, den = out[2].split("/")
        fps = float(num) / float(den)
    except (IndexError, ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "width": int(out[0]) if out and out[0] else 0,
        "height": int(out[1]) if len(out) > 1 and out[1] else 0,
        "fps": fps,
        "nb_frames": int(out[3]) if len(out) > 3 and out[3].isdigit() else None,
        "duration": float(out[4]) if len(out) > 4 and out[4] not in ("", "N/A") else None,
    }


def decode(
    path: str | Path,
    start_s: float,
    end_s: float,
    fps: int = FPS,
    grey: bool = False,
    width: int = W,
    height: int = H,
) -> np.ndarray:
    """Frames of [start_s, end_s) at `fps`, scaled to width x height. uint8 [n, H, W(, 3)]."""
    vf = f"fps={fps},scale={width}:{height}"
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-threads",
        "1",
        "-ss",
        f"{start_s:.3f}",
        "-t",
        f"{max(end_s - start_s, 0.05):.3f}",
        "-i",
        str(path),
        "-vf",
        vf,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray" if grey else "rgb24",
        "-",
    ]
    # streamed frame by frame into one array (the same bytes as reading the pipe whole, at a third
    # of the memory)
    per = width * height * (1 if grey else 3)
    cap = int(np.ceil(max(end_s - start_s, 0.05) * fps)) + 4
    arr = np.empty((cap, per), np.uint8)
    n = 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            if n == len(arr):
                arr = np.concatenate([arr, np.empty((cap, per), np.uint8)])
            got = proc.stdout.readinto(memoryview(arr[n]))
            while got and got < per:
                more = proc.stdout.readinto(memoryview(arr[n])[got:])
                if not more:
                    break
                got += more
            if got < per:
                break
            n += 1
        rc = proc.wait(timeout=600)
    finally:
        if proc.poll() is None:
            proc.kill()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    arr = arr[:n] if n == len(arr) else arr[:n].copy()
    return arr.reshape(n, height, width) if grey else arr.reshape(n, height, width, 3)


def encode_for_sam(
    path: str | Path, start_s: float, end_s: float, out: Path, fps: int = FPS, width: int = W
) -> bytes:
    """Smoke G's encode, unchanged: the window at `fps`, `width` wide, libx264 CRF 20, no audio.
    Returns the bytes.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{start_s:.3f}",
            "-t",
            f"{end_s - start_s:.3f}",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},scale={width}:-2",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(out),
        ]
    )
    return out.read_bytes()


def jpeg_of(frame_rgb: np.ndarray, quality: int = 4) -> bytes:
    """One frame as JPEG through ffmpeg (no PIL dependency)."""
    h, w = frame_rgb.shape[:2]
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-i",
        "-",
        "-frames:v",
        "1",
        "-q:v",
        str(quality),
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    return subprocess.run(cmd, input=frame_rgb.tobytes(), capture_output=True, check=True).stdout


def frames_sha(frames: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(frames).tobytes()).hexdigest()


def thumbs(path: str | Path, start_s: float, end_s: float, n: int, width: int = 320) -> np.ndarray:
    """n small RGB frames spread over the window (broadcast scan and shot-cut gates)."""
    dur = max(end_s - start_s, 0.1)
    fps = n / dur
    h = int(round(width * 9 / 16))
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-threads",
        "1",
        "-ss",
        f"{start_s:.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        str(path),
        "-vf",
        f"fps={fps:.6f},scale={width}:{h}",
        "-frames:v",
        str(n),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    raw = _run(cmd, timeout=900)
    per = width * h * 3
    k = len(raw) // per
    return np.frombuffer(raw[: k * per], np.uint8).reshape(k, h, width, 3)
