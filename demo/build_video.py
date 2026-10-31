"""Build the demo video: one still per script line, each held until the voice reaches the next.

    python demo/build_video.py --audio take.webm --cues take.cues.json --out demo/faultline-demo.mp4

`--cues` is the JSON a prompter writes while the take is recorded: a list under "cues", one per
heading reached, each with the second it was reached ("t"), in the order of the stills. Still N is
shown from cue N until cue N+1, and the last still until the audio ends. A take that reached fewer
headings than there are stills shows the remaining stills in the last stretch, split evenly, so the
film is never short a still. Needs ffmpeg and ffprobe on the path. Standard library only.
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
        help="folder of NN-*.png stills (default demo/STILLS)",
    )
    ap.add_argument("--out", required=True, type=Path, help="the mp4 to write")
    ap.add_argument(
        "--lead", type=float, default=0.6, help="seconds of the first still before the voice starts"
    )
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args(argv)

    stills = sorted(p for p in a.stills.iterdir() if p.suffix.lower() == ".png")
    cues = json.loads(a.cues.read_text(encoding="utf-8"))["cues"]
    cue_times = [float(c["t"]) for c in cues]
    voice = audio_seconds(a.audio)
    end = voice + a.lead + 1.0
    shots = plan(stills, cue_times, end, a.lead)

    with tempfile.TemporaryDirectory() as td:
        listing = Path(td) / "shots.txt"
        lines = []
        for still, shown in shots:
            lines.append(f"file '{still.as_posix()}'")
            lines.append(f"duration {shown:.3f}")
        lines.append(f"file '{shots[-1][0].as_posix()}'")  # concat demuxer: repeat the last file
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-itsoffset",
            f"{a.lead:.3f}",
            "-i",
            str(a.audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
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
    print(f"wrote {a.out} : {len(shots)} stills over {total:.1f} s, voice {voice:.1f} s")
    for i, (still, shown) in enumerate(shots, 1):
        print(f"  {i:2d} {still.name:28s} {shown:6.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
