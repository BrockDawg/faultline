"""Build silent 2 fps protest replays from the already stored racing review frames.

    uv run python scripts/site_clips.py --sources data/site/sources.json --out site/data/video
    uv run python scripts/site_racing_videos.py

These are sampled replays, not continuous race recordings. Frames are used in their recorded
stream-time order; no frames, audio, labels, or rulings are synthesized.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/site/racing/preds-arm2.jsonl"
FRAMES = SOURCE.with_name(SOURCE.name + ".frames")
OUT = ROOT / "site/data/video"
DATA = ROOT / "site/data"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to build the protest replays")
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    OUT.mkdir(parents=True, exist_ok=True)
    protests: dict[str, dict[str, object]] = {}
    manifest_path = OUT / "videos.json"
    if not manifest_path.is_file():
        raise SystemExit("run scripts/site_clips.py first to build the forklift video manifest")
    existing = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    )
    videos = [
        item
        for item in existing.get("videos", [])
        if isinstance(item, dict) and item.get("kind") != "racing_review"
    ]
    for row in rows:
        frames = row.get("frames") or []
        if not frames:
            continue
        frames = sorted(frames, key=lambda item: float(item["stream_s"]))
        paths = []
        for frame in frames:
            path = FRAMES / (frame["sha256"] + ".jpg")
            if not path.is_file() or sha256(path) != frame["sha256"]:
                raise SystemExit(f"missing or changed source frame: {path.name}")
            paths.append(path)
        name = f"racing-protest-{row['id']}.mp4"
        output = OUT / name
        with tempfile.TemporaryDirectory(prefix="faultline-race-frames-") as temp:
            concat = Path(temp) / "frames.txt"
            concat.write_text(
                "".join(f"file '{path.as_posix()}'\nduration 0.5\n" for path in paths)
                + f"file '{paths[-1].as_posix()}'\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat),
                    "-fps_mode",
                    "vfr",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "25",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(output),
                ],
                check=True,
            )
        source_hashes = [frame["sha256"] for frame in frames]
        protests[str(row["id"])] = {
            "video": f"video/{name}",
            "frames": len(frames),
            "source_sha256": source_hashes,
        }
        videos.append(
            {
                "file": f"video/{name}",
                "sha256": sha256(output),
                "kind": "racing_review",
                "protest": str(row["id"]),
                "source_sha256": source_hashes,
            }
        )
    (DATA / "racing" / "media.json").parent.mkdir(parents=True, exist_ok=True)
    (DATA / "racing" / "media.json").write_text(
        json.dumps({"schema": 1, "protests": protests}, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps({"schema": 1, "videos": videos}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Built {len(protests)} silent racing protest replays at 2 fps.")


if __name__ == "__main__":
    main()
