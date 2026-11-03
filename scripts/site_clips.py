"""Cut each demo-shift window's footage into a short web video for the live page.

Run from the repo root:
    uv run python scripts/site_clips.py --sources data/site/sources.json --out site/data/video

For each window in `shift.json` (the bundle beside --out) it encodes exactly the footage the judge
read: the clip, the start and the length taken from the shift run's own record (the folder
`sources.json` names as `shift.output.path`):
  - `windows.jsonl` names the window's clip file, its sha256, entry and record hash;
  - `entries/<entry>.json` holds the item the judge was given (`start_s`, `end_s`) and, in
    `gates.window_s`, the seconds the judge actually read (the window cut to the clip's end and to
    the frames decoded). That length is used as is. If it is missing, or longer than the clip
    allows, or the record disagrees with itself, the run stops: a length is never guessed.

Synthetic only. A window is encoded only when `site_sweep._proven_synthetic` says the shift record
shows it read a clip from a `synthetic` folder (the same proof the sweep holds every shift frame
to), and its clip is not in `index.json`'s real group. Anything else is skipped and listed. Real
footage is never encoded.

Each video: H.264 main, 640 wide, yuv420p, no audio, subtitles, data or metadata, fast start,
bit-exact flags and one thread, so a rerun writes the same bytes. Output (rebuilt each run):
  <window id>.mp4
  videos.json  {schema: 1, videos: [{file, window, clip, start_s, duration_s, fps, width, height,
               bytes, sha256, audio: false}]}, `file` relative to the bundle folder; fps, width,
               height and audio are read back from each written file with ffprobe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import site_sweep  # noqa: E402

OUT_W = 640
CRF = 27
TOLERANCE_S = 0.001  # the record rounds seconds to 3 places


class ClipsError(Exception):
    """The record cannot give a window's footage honestly: the run stops, nothing is guessed."""


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=True,
    ).stdout
    return json.loads(out)


def _rate(text: str) -> float:
    num, _, den = text.partition("/")
    return float(num) / float(den or 1)


def encode_cmd(clip: Path, start: float, duration: float, dest: Path) -> list[str]:
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(clip),
        "-t",
        f"{duration:.3f}",
        "-an",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-vf",
        f"scale={OUT_W}:-2,format=yuv420p",
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-preset",
        "medium",
        "-crf",
        str(CRF),
        "-threads",
        "1",
        "-movflags",
        "+faststart",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        str(dest),
    ]


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def plan(sources: Path, bundle: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """(jobs, skipped). Each job: window, clip id, clip path, start_s, duration_s."""
    src = _read_json(sources)
    folder = ((src.get("shift") or {}).get("output") or {}).get("path")
    if not isinstance(folder, str) or not folder:
        raise ClipsError(f"{sources}: no shift.output.path, so there is no shift record")
    shift_dir = Path(folder)
    if not shift_dir.is_absolute():
        shift_dir = sources.parent / shift_dir
    record = site_sweep.shift_record(sources)
    if not record:
        raise ClipsError(f"{shift_dir}: no windows.jsonl, so no window can be proven")
    shift = _read_json(bundle / "shift.json")
    index_path = bundle / "index.json"
    index = _read_json(index_path) if index_path.is_file() else {}
    real = {
        c.get("id")
        for c in index.get("clips") or []
        if isinstance(c, dict) and (c.get("kind") == "real" or c.get("group") == "real")
    }
    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for w in shift.get("windows") or []:
        wid = w.get("window")
        if not isinstance(wid, str) or not site_sweep._WINDOW_FOLDER.match(wid):
            skipped.append({"window": str(wid), "why": "not a wNN- window id"})
            continue
        if not isinstance(w.get("clip"), str):
            skipped.append({"window": wid, "why": "the window names no clip"})
            continue
        if w["clip"] in real:
            skipped.append({"window": wid, "why": "its clip is in the real group"})
            continue
        if not site_sweep._proven_synthetic(w, record):
            skipped.append({"window": wid, "why": "not proven synthetic by the shift record"})
            continue
        row = record[wid]
        entry_path = shift_dir / "entries" / f"{row['entry']}.json"
        if not entry_path.is_file():
            raise ClipsError(f"{wid}: the record has no entry {row['entry']}")
        entry = _read_json(entry_path)
        item = entry.get("item") or {}
        gates = entry.get("gates") or {}
        csha = row.get("clip_sha256")
        if entry.get("entry") != row["entry"] or entry.get("clip_sha256") != csha or not csha:
            raise ClipsError(f"{wid}: the entry and windows.jsonl name different clips")
        try:
            start, end = float(item["start_s"]), float(item["end_s"])
            secs = float(gates["window_s"])
        except (KeyError, TypeError, ValueError):
            raise ClipsError(f"{wid}: the record holds no start, end or window_s") from None
        if abs(start - float(row["start_s"])) > TOLERANCE_S or (
            abs(end - float(row["end_s"])) > TOLERANCE_S
        ):
            raise ClipsError(f"{wid}: the entry's window differs from windows.jsonl")
        clip = Path(row["clip"])
        if not clip.is_file() or sha256_file(clip) != csha:
            raise ClipsError(f"{wid}: the clip file is missing or its bytes changed")
        fmt = ffprobe(clip).get("format") or {}
        dur = float(fmt.get("duration") or end)
        span = min(end, dur) - start
        if not (0 < secs <= span + TOLERANCE_S):
            raise ClipsError(f"{wid}: window_s {secs} does not fit the clip ({span:.3f} s)")
        jobs.append(
            {"window": wid, "clip": w["clip"], "path": clip, "start_s": start, "duration_s": secs}
        )
    return jobs, skipped


def _clean(out: Path) -> None:
    if out.is_dir():
        for f in out.glob("*.mp4"):
            f.unlink()
        (out / "videos.json").unlink(missing_ok=True)


def build(sources: Path, out: Path, workers: int = 4) -> dict[str, Any]:
    bundle = out.parent
    jobs, skipped = plan(sources, bundle)
    _clean(out)
    out.mkdir(parents=True, exist_ok=True)

    def run(job: dict[str, Any]) -> None:
        dest = out / f"{job['window']}.mp4"
        subprocess.run(
            encode_cmd(job["path"], job["start_s"], job["duration_s"], dest),
            capture_output=True,
            check=True,
        )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(run, jobs))

    videos = []
    for job in sorted(jobs, key=lambda j: j["window"]):
        dest = out / f"{job['window']}.mp4"
        probe = ffprobe(dest)
        streams = probe.get("streams") or []
        video = [s for s in streams if s.get("codec_type") == "video"]
        if len(video) != 1 or len(streams) != 1:
            raise ClipsError(f"{dest.name}: wrote {len(streams)} streams, not one video stream")
        fps = _rate(str(video[0].get("r_frame_rate") or "0/1"))
        got = float((probe.get("format") or {}).get("duration") or 0)
        if fps <= 0 or abs(got - job["duration_s"]) > 1.0 / fps + TOLERANCE_S:
            raise ClipsError(f"{dest.name}: {got} s written for a {job['duration_s']} s window")
        videos.append(
            {
                "file": f"{out.name}/{dest.name}",
                "window": job["window"],
                "clip": job["clip"],
                "start_s": round(job["start_s"], 3),
                "duration_s": round(job["duration_s"], 3),
                "fps": round(fps, 3),
                "width": int(video[0]["width"]),
                "height": int(video[0]["height"]),
                "bytes": dest.stat().st_size,
                "sha256": sha256_file(dest),
                "audio": False,
            }
        )
    (out / "videos.json").write_text(
        json.dumps({"schema": 1, "videos": videos}, indent=1, sort_keys=True, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sizes = [v["bytes"] for v in videos]
    return {
        "videos": len(videos),
        "skipped": skipped,
        "bytes": sum(sizes),
        "min_bytes": min(sizes) if sizes else 0,
        "max_bytes": max(sizes) if sizes else 0,
        "manifest_sha256": sha256_file(out / "videos.json"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="the video folder inside the bundle")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg and ffprobe are needed on PATH", file=sys.stderr)
        return 2
    try:
        res = build(a.sources, a.out, a.workers)
    except ClipsError as exc:
        print(f"site clips stopped: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
