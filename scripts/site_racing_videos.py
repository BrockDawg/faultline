"""Build silent, continuous race excerpts for the eight public protest reviews.

The clips use the exact stream-time range represented by each stored frame sequence.
Broadcast overlays are masked with the same rules used when the review frames were made.
Original source links are included in the public media manifest.

Run from the repo root:
    uv run python scripts/site_racing_videos.py --racing-data <private racing data directory> \
        --video-data <original video directory>
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/site/racing/preds-arm2.jsonl"
FRAMES = SOURCE.with_name(SOURCE.name + ".frames")
OUT = ROOT / "site/data/video"
DATA = ROOT / "site/data"
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CONTEXT_SECONDS = 3.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_url(source: Path, aliases: dict[str, str]) -> str:
    stem = source.stem
    if YOUTUBE_ID.fullmatch(stem):
        return f"https://www.youtube.com/watch?v={stem}"
    url = aliases.get(stem.removeprefix("ph"))
    if not url:
        raise SystemExit(f"no original source link is recorded for {source.name}")
    parsed = urlparse(url)
    if parsed.netloc.casefold() in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if not video_id and parsed.path.startswith("/live/"):
            video_id = parsed.path.removeprefix("/live/").split("/", 1)[0]
        if not video_id and parsed.path.startswith("/shorts/"):
            video_id = parsed.path.removeprefix("/shorts/").split("/", 1)[0]
        if YOUTUBE_ID.fullmatch(video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    if parsed.netloc.casefold() == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
        if YOUTUBE_ID.fullmatch(video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    raise SystemExit(f"the recorded source for {source.name} is not a YouTube video")


def _stream_sources(racing_data: Path) -> tuple[dict[str, Path], dict[str, list[str]]]:
    league = json.loads((racing_data / "league.json").read_text(encoding="utf-8"))
    masks = json.loads((racing_data / "masks.json").read_text(encoding="utf-8"))
    by_session = {
        key: Path(value["stream"])
        for key, value in league["sessions"].items()
        if isinstance(value, dict) and isinstance(value.get("stream"), str)
    }
    mask_by_session = {
        key: list(masks.get("default", []))
        + [
            "drawbox=x=1000:y=0:w=280:h=120:color=black:t=fill",
            "drawbox=x=1000:y=500:w=280:h=220:color=black:t=fill",
        ]
        + list(masks.get("sessions", {}).get(key, []))
        for key in by_session
    }
    return by_session, mask_by_session


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--racing-data", type=Path, required=True)
    parser.add_argument("--video-data", type=Path, required=True)
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to build continuous racing excerpts")
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        raise SystemExit("the stored racing review records are missing")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "videos.json"
    if not manifest_path.is_file():
        raise SystemExit("run scripts/site_clips.py first to build the forklift video manifest")
    existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    videos = [
        item
        for item in existing.get("videos", [])
        if isinstance(item, dict) and item.get("kind") != "racing_review"
    ]
    stream_by_session, mask_by_session = _stream_sources(args.racing_data)
    # The URLs file sits alongside the original video files in the steward corpus.
    aliases: dict[str, str] = {}
    urls_path = args.video_data / "urls.tsv"
    if not urls_path.is_file():
        raise SystemExit("the original video source list is missing")
    for line in urls_path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split("\t", 1)
        if len(fields) == 2:
            aliases[fields[0]] = fields[1]

    protests: dict[str, dict[str, object]] = {}
    for row in rows:
        frames = sorted(row.get("frames") or [], key=lambda item: float(item["stream_s"]))
        if not frames:
            continue
        session = str((row.get("window") or {}).get("session", ""))
        source = stream_by_session.get(session)
        if source is None or not source.is_file():
            raise SystemExit(f"the original stream is unavailable for protest {row['id']}")
        for frame in frames:
            path = FRAMES / (frame["sha256"] + ".jpg")
            if not path.is_file() or sha256(path) != frame["sha256"]:
                raise SystemExit(f"missing or changed source frame: {path.name}")
        times = [float(frame["stream_s"]) for frame in frames]
        intervals = [b - a for a, b in zip(times, times[1:], strict=False) if b > a]
        if not intervals:
            raise SystemExit(f"protest {row['id']} has no usable frame interval")
        step = sorted(intervals)[len(intervals) // 2]
        review_start_s = times[0]
        review_duration_s = times[-1] - review_start_s + step
        start_s = max(0.0, review_start_s - CONTEXT_SECONDS)
        duration_s = review_duration_s + (review_start_s - start_s) + CONTEXT_SECONDS
        filters = mask_by_session.get(session, [])
        if not filters:
            raise SystemExit(f"the broadcast masks are missing for protest {row['id']}")
        name = f"racing-protest-{row['id']}.mp4"
        output = OUT / name
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start_s:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration_s:.3f}",
                "-vf",
                ",".join(filters),
                "-an",
                "-map_metadata",
                "-1",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
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
        source_link = f"{source_url(source, aliases)}&t={int(start_s)}s"
        protests[str(row["id"])] = {
            "video": f"video/{name}",
            "start_s": start_s,
            "duration_s": duration_s,
            "review_start_s": review_start_s,
            "review_duration_s": review_duration_s,
            "source_url": source_link,
            "source_sha256": source_hashes,
        }
        videos.append(
            {
                "file": f"video/{name}",
                "sha256": sha256(output),
                "kind": "racing_review",
                "protest": str(row["id"]),
                "start_s": start_s,
                "duration_s": duration_s,
                "review_start_s": review_start_s,
                "review_duration_s": review_duration_s,
                "source_url": source_link,
                "source_sha256": source_hashes,
            }
        )
    (DATA / "racing").mkdir(parents=True, exist_ok=True)
    (DATA / "racing/media.json").write_text(
        json.dumps({"schema": 1, "protests": protests}, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps({"schema": 1, "videos": videos}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Built {len(protests)} continuous, silent racing excerpts with source links.")


if __name__ == "__main__":
    main()
