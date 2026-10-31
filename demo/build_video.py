"""Build the demo video: one still per script line, each held until the voice reaches the next.

    python demo/build_video.py --audio take.webm --cues take.cues.json --out demo/faultline-demo.mp4

`--cues` is the JSON a prompter writes while the take is recorded: a list under "cues", one per
heading reached, each with the second it was reached ("t"), in the order of the stills. Still N is
shown from cue N until cue N+1, and the last still until the audio ends. A take that reached fewer
headings than there are stills shows the remaining stills in the last stretch, split evenly, so the
film is never short a still. Needs ffmpeg and ffprobe on the path. Standard library only.

`--stills` may instead name a folder of NN-*.mp4 segments (the moving cut, demo/VIDEO): when the
folder holds any mp4 the segments are used and its PNGs are ignored. Each segment plays from its
start for its stretch, cut short when the voice moves on first and its last frame held when the
voice runs longer than the segment. For the moving cut, add `--stills demo/VIDEO` to the command
above.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STILLS = HERE / "STILLS"
W, H = 1920, 1080


def audio_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def plan(
    stills: list[Path], cue_times: list[float], end: float, lead: float
) -> list[tuple[Path, float]]:
    """(still, seconds shown) per still, in order. The first still starts at 0 and the audio
    is delayed by `lead`."""
    if not stills:
        raise SystemExit("no stills found")
    times = [max(0.0, t) + lead for t in cue_times[: len(stills)]]
    if not times or times[0] > lead:
        times.insert(0, 0.0)
        times = times[: len(stills)]
    times[0] = 0.0
    missing = len(stills) - len(times)
    if missing > 0:
        last = times[-1]
        step = max(0.0, (end - last)) / (missing + 1)
        times += [last + step * (k + 1) for k in range(missing)]
    bounds = times + [end]
    plan_ = []
    for i, still in enumerate(stills):
        shown = max(0.5, bounds[i + 1] - bounds[i])
        plan_.append((still, shown))
    return plan_


def media(folder: Path) -> list[Path]:
    """The folder's mp4 segments in name order when it holds any, else its PNG stills."""
    files = sorted(p for p in folder.iterdir() if p.is_file())
    mp4 = [p for p in files if p.suffix.lower() == ".mp4"]
    return mp4 or [p for p in files if p.suffix.lower() == ".png"]


def still_inputs(shots: list[tuple[Path, float]], td: Path) -> list[str]:
    """ffmpeg input arguments for PNG stills: one concat list, each still for its stretch."""
    listing = td / "shots.txt"
    lines = []
    for still, shown in shots:
        lines.append(f"file '{still.as_posix()}'")
        lines.append(f"duration {shown:.3f}")
    lines.append(f"file '{shots[-1][0].as_posix()}'")  # concat demuxer: repeat the last file
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ["-f", "concat", "-safe", "0", "-i", str(listing)]


def segment_graph(shots: list[tuple[Path, float]], fps: int) -> str:
    """A filter graph that cuts segment i to its stretch (holding its last frame when the stretch
    is longer than the segment) and joins them in order, as [v]."""
    parts = []
    for i, (_, shown) in enumerate(shots):
        parts.append(
            f"[{i}:v]fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,"
            f"tpad=stop_mode=clone:stop_duration={shown:.3f},"
            f"trim=duration={shown:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
    joined = "".join(f"[v{i}]" for i in range(len(shots)))
    parts.append(f"{joined}concat=n={len(shots)}:v=1:a=0[v]")
    return ";".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--audio", required=True, type=Path, help="the voice take (webm, m4a, wav, mp3)"
    )
    ap.add_argument(
        "--cues", required=True, type=Path, help="the prompter's cues JSON for that take"
    )
    ap.add_argument(
        "--stills",
        type=Path,
        default=STILLS,
        help="folder of NN-*.png stills, or of NN-*.mp4 segments (default demo/STILLS)",
    )
    ap.add_argument("--out", required=True, type=Path, help="the mp4 to write")
    ap.add_argument(
        "--lead", type=float, default=0.6, help="seconds of the first still before the voice starts"
    )
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args(argv)

    stills = media(a.stills)
    moving = bool(stills) and stills[0].suffix.lower() == ".mp4"
    cues = json.loads(a.cues.read_text(encoding="utf-8"))["cues"]
    cue_times = [float(c["t"]) for c in cues]
    voice = audio_seconds(a.audio)
    end = voice + a.lead + 1.0
    shots = plan(stills, cue_times, end, a.lead)

    with tempfile.TemporaryDirectory() as td:
        if moving:
            inputs = [arg for still, _ in shots for arg in ("-i", str(still))]
            video = ["-filter_complex", segment_graph(shots, a.fps), "-map", "[v]"]
        else:
            inputs = still_inputs(shots, Path(td))
            video = ["-map", "0:v:0"]
        voice_in = len(shots) if moving else 1
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-itsoffset",
            f"{a.lead:.3f}",
            "-i",
            str(a.audio),
            *video,
            "-map",
            f"{voice_in}:a:0",
            "-r",
            str(a.fps),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-t",
            f"{end:.3f}",
            "-movflags",
            "+faststart",
            str(a.out),
        ]
        subprocess.run(cmd, check=True)
    total = sum(s for _, s in shots)
    kind = "segments" if moving else "stills"
    print(f"wrote {a.out} : {len(shots)} {kind} over {total:.1f} s, voice {voice:.1f} s")
    for i, (still, shown) in enumerate(shots, 1):
        print(f"  {i:2d} {still.name:28s} {shown:6.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
