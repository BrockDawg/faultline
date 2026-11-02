"""Extract the frames the demo page shows, blur the real-footage faces, write the manifests.

Run from the repo root:
    uv run python scripts/site_frames.py --sources data/site/sources.json --out site/data/frames

For each clip in each record root that `sources.json` names (shipped, graded, real) it writes a
poster and every frame a ruling card will show, 640 px wide JPEG:
  1. the frames the ruling names (at most three: first, middle, last), source "ruling";
  2. else the frames shown to the model for that window (the `frames` list of the first stored
     note*.json, else read-k.json), source "model";
  3. else the window's frames 12, 60 and 108, source "window".
Frame numbers count from the window start at 24 a second, so frame n sits at
t = start_s + n / 24. Each frame is cut by seeking to that time, never by frame count, because a
real clip need not run at 24 fps.

Real footage is never written unblurred. Each real frame takes the person box SAM tracked
(the nearest box within 2 of its 12 fps mask frames, all objects on that frame): widened 15% each
side, from 5% above the box top down to 60% of its height, pixelated by 24 and blurred
(Gaussian, sigma 18) at 1280x720, then scaled to 640 wide. A real frame with no box near it is
not written; the manifests say why. `blurred.json` lists every real frame with `checked: false`.
Only a person's eye sets it true; this script never does.

Output (all under --out, rebuilt on every run, byte-identical on a rerun):
  <clip id>/<n>.jpg, <clip id>/poster.jpg, and <shift window id>/poster.jpg per shift window
  frames.json   every JPEG: file (relative to the data folder, frames/<clip>/<n>.jpg), clip,
                frame (or "poster", with at_frame), t_s, sha256, kind, blurred
                plus `rulings`: per root and clip, per rule, the frames and their source
  blurred.json  every real-footage JPEG with its boxes and `checked: false`, and what was dropped
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from faultline.adapters.video.shift import ruling_frames
from faultline.adapters.video.wonder import EMPTY_FRAMES, NOTE_ATTEMPTS, READ_RUNS, _win

ROOTS = ("shipped", "graded", "real")
FRAME_RATE = 24  # ruling frame numbers are given at this rate, from the window start
MASK_RATE = 12  # SAM's boxes are kept at this rate, from the window start
OUT_W = 640
BLUR_W, BLUR_H = 1280, 720  # the boxes' own frame size
BOX_REACH = 2  # mask frames: a box further than this from the frame does not cover it
PIXELATE = 24
SIGMA = 18
BLUR_METHOD = (
    "per frame, every SAM person_track box on the nearest mask frame within 2 (12 fps): "
    "widened 15% each side, from 5% above the box top to 60% of its height; pixelated by 24 "
    "then scaled back bilinear, then Gaussian blur sigma 18, at 1280x720; then 640 wide. "
    "A frame with no box within 2 mask frames is not written."
)
BITEXACT = ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]


# ---------------------------------------------------------------- inputs
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _paths_under(node: Any) -> list[Path]:
    """Every existing .mp4 file, or folder, a string in this part of sources.json names."""
    out: list[Path] = []
    if isinstance(node, dict):
        for v in node.values():
            out += _paths_under(v)
    elif isinstance(node, list):
        for v in node:
            out += _paths_under(v)
    elif isinstance(node, str) and ("/" in node or "\\" in node):
        p = Path(node)
        if p.is_dir() or (p.is_file() and p.suffix.lower() == ".mp4"):
            out.append(p)
    return out


class ClipIndex:
    """Finds a clip file by its sha256 among the files sources.json names (hashed on first need)."""

    def __init__(self, places: list[Path]):
        self.places = places
        self._by_sha: dict[str, Path] | None = None

    def _build(self) -> dict[str, Path]:
        files: set[Path] = set()
        for p in self.places:
            if p.is_dir():
                files |= {f for f in p.rglob("*") if f.is_file() and f.suffix.lower() == ".mp4"}
            elif p.is_file():
                files.add(p)
        by: dict[str, Path] = {}
        for f in sorted(files, key=lambda x: x.as_posix()):
            by.setdefault(sha256_file(f), f)
        return by

    def find(self, sha: str, hint: str | None) -> Path | None:
        if hint:
            p = Path(hint)
            if p.is_file() and sha256_file(p) == sha:
                return p
        if self._by_sha is None:
            self._by_sha = self._build()
        return self._by_sha.get(sha)


def probe(clip: Path) -> tuple[float, float]:
    """(duration in seconds, frame rate) of the clip's first video stream."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate,duration:format=duration",
            "-of",
            "json",
            str(clip),
        ],
        capture_output=True,
        check=True,
    ).stdout
    j = json.loads(out)
    st = (j.get("streams") or [{}])[0]
    num, _, den = str(st.get("r_frame_rate") or "24/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else float(FRAME_RATE)
    dur = st.get("duration") or (j.get("format") or {}).get("duration") or 0
    return float(dur), fps


def person_boxes(box_dirs: list[Path], csha: str) -> dict[int, list[tuple[int, int, int, int]]]:
    """SAM's person_track boxes by 12 fps mask frame, from the first record that holds them."""
    for base in box_dirs:
        cd = base / "clips" / csha
        reply = cd / "person_track.txt"
        if not reply.is_file():
            continue
        npz = cd / "masks" / f"{hashlib.sha256(reply.read_bytes()).hexdigest()}.npz"
        if not npz.is_file():
            continue
        out: dict[int, list[tuple[int, int, int, int]]] = {}
        with np.load(npz) as z:
            for k in sorted(z.files):
                if k.startswith("b_"):
                    _, f, _oid = k.split("_", 2)
                    b = z[k]
                    out.setdefault(int(f), []).append((int(b[0]), int(b[1]), int(b[2]), int(b[3])))
        return out
    return {}


def boxes_for(
    boxes: dict[int, list[tuple[int, int, int, int]]], n: int
) -> tuple[int | None, list[tuple[int, int, int, int]]]:
    """The boxes on the mask frame nearest frame n (24 fps), within BOX_REACH mask frames."""
    m = n * MASK_RATE / FRAME_RATE
    near = [k for k in boxes if abs(k - m) <= BOX_REACH]
    if not near:
        return None, []
    k = min(near, key=lambda x: (abs(x - m), x))
    return k, boxes[k]


def blur_region(b: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    """The region seg_real blurs for one person box (x0, y0, x1, y1), or None if empty."""
    x0, y0, x1, y1 = b
    bh = y1 - y0
    r = (
        max(0, int(x0 - 0.15 * (x1 - x0))),
        max(0, int(y0 - 0.05 * bh)),
        min(BLUR_W, int(x1 + 0.15 * (x1 - x0))),
        min(BLUR_H, int(y0 + 0.6 * bh)),
    )
    return r if r[2] > r[0] and r[3] > r[1] else None


def model_frames(record: Path, csha: str, item: dict) -> list[int]:
    """The frames shown to the model for this window: the first stored note, else read."""
    d = record / "clips" / csha / "wonder" / _win(item)
    names = ["note.json"] + [f"note-{a}.json" for a in range(2, NOTE_ATTEMPTS + 1)]
    names += [f"read-{k}.json" for k in range(1, READ_RUNS + 1)]
    for name in names:
        p = d / name
        if p.is_file():
            fr = json.loads(p.read_text(encoding="utf-8")).get("frames") or []
            if fr:
                return [int(x) for x in fr]
    return []


def pick3(fr: list[int]) -> list[int]:
    return ruling_frames({"frames": fr})


# ---------------------------------------------------------------- ffmpeg
def _seek(t: float, fps: float) -> str:
    """Half a source frame early, so the first frame at or after it is the one nearest t."""
    return f"{max(0.0, t - 0.5 / fps):.6f}"


def cut(clip: Path, t: float, fps: float, dest: Path, regions: list | None) -> None:
    """One frame at time t, 640 wide; with regions (real footage) the blur is applied first."""
    if regions is None:
        vf = ["-vf", f"scale={OUT_W}:-2"]
    else:
        if not regions:
            raise ValueError("a real frame is never written without a blur region")
        g = [f"[0:v]scale={BLUR_W}:{BLUR_H},format=rgb24[v0]"]
        for i, (x0, y0, x1, y1) in enumerate(regions):
            w, h = x1 - x0, y1 - y0
            sw, sh = max(1, w // PIXELATE), max(1, h // PIXELATE)
            g.append(f"[v{i}]split[a{i}][b{i}]")
            g.append(
                f"[b{i}]crop={w}:{h}:{x0}:{y0}:exact=1,scale={sw}:{sh}:flags=area,"
                f"scale={w}:{h}:flags=bilinear,gblur=sigma={SIGMA}[m{i}]"
            )
            g.append(f"[a{i}][m{i}]overlay={x0}:{y0}:format=rgb[v{i + 1}]")
        g.append(f"[v{len(regions)}]scale={OUT_W}:-2[out]")
        vf = ["-filter_complex", ";".join(g), "-map", "[out]"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-ss",
            _seek(t, fps),
            "-i",
            str(clip),
            "-frames:v",
            "1",
            *vf,
            "-q:v",
            "4",
            *BITEXACT,
            "-y",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )


# ---------------------------------------------------------------- the run
def _clean(out: Path) -> None:
    """Remove what an earlier run wrote, so the tree always equals the manifest."""
    if not out.is_dir():
        return
    for f in out.rglob("*.jpg"):
        f.unlink()
    for name in ("frames.json", "blurred.json"):
        (out / name).unlink(missing_ok=True)
    for d in sorted((p for p in out.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()


def _write_json(p: Path, obj: Any) -> None:
    p.write_text(
        json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _place(
    jobs: dict[str, dict],
    dropped: list[dict],
    n: int,
    name: str,
    cid: str,
    clip: Path,
    fps: float,
    start: float,
    real: bool,
    boxes: dict,
    root: str,
) -> bool:
    """Queue frame n of a clip as <cid>/<name>.jpg; a real frame with no box is dropped."""
    t = start + n / FRAME_RATE
    regions = None
    bmeta: dict[str, Any] = {}
    if real:
        k, bx = boxes_for(boxes, n)
        regions = [r for r in (blur_region(b) for b in bx) if r is not None]
        if k is None or not regions:
            dropped.append(
                {
                    "clip": cid,
                    "frame": n,
                    "root": root,
                    "why": "no person box within 2 mask frames, so the face cannot be covered",
                }
            )
            return False
        bmeta = {
            "box_frame": k,
            "boxes": [list(b) for b in bx],
            "regions": [list(r) for r in regions],
        }
    poster = name == "poster"
    jobs.setdefault(
        f"{cid}/{name}.jpg",
        {
            "clip": clip,
            "t": t,
            "fps": fps,
            "regions": regions,
            "meta": {
                "clip": cid,
                "frame": "poster" if poster else n,
                **({"at_frame": n} if poster else {}),
                "t_s": round(t, 4),
                "kind": "real" if real else "synthetic",
                "blurred": real,
                **bmeta,
            },
        },
    )
    return True


def build(
    sources_path: Path, out: Path, only: set[str] | None = None, workers: int = 4
) -> dict[str, Any]:
    """Write the frames and manifests; returns counts for the caller to print."""
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    base = sources_path.parent
    roots = sources.get("roots") or {}
    blur = sources.get("blur") or {}
    places = _paths_under(
        {k: {"clip_mp4s": v.get("clip_mp4s"), "clips": v.get("clips")} for k, v in roots.items()}
    )
    index = ClipIndex(places)
    box_dirs = [Path(blur["person_boxes"])] if blur.get("person_boxes") else []

    jobs: dict[str, dict] = {}  # file -> job (clip, t, fps, regions, meta)
    rulings: dict[str, dict] = {}
    dropped: list[dict] = []
    missing: list[str] = []
    posters_done: set[str] = set()
    seen: set[str] = set()  # clip ids already taken from an earlier root (shipped first)

    for root in ROOTS:
        if root not in roots or not roots[root].get("preds"):
            continue
        preds = (base / roots[root]["preds"]).resolve()
        record = preds.parent
        real = root == "real"
        dirs = box_dirs + [record]
        for line in preds.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            pred = json.loads(line)
            cid = pred["id"]
            if only and cid not in only:
                continue
            if cid in seen:  # a featured clip comes from the shipped root only
                continue
            seen.add(cid)
            entry = json.loads((record / "entries" / f"{pred['entry']}.json").read_text("utf-8"))
            item, csha = entry["item"], entry["clip_sha256"]
            clip = index.find(csha, item.get("clip"))
            if clip is None:
                missing.append(f"{root}/{cid}")
                continue
            dur, fps = probe(clip)
            start, end = float(item.get("start_s", 0.0)), float(item.get("end_s", 0.0))
            count = max(0, int(round((min(end, dur or end) - start) * FRAME_RATE)))
            boxes = person_boxes(dirs, csha) if real else {}

            def clamp(fr: list[int], count: int = count) -> list[int]:
                return sorted({min(max(int(i), 0), count - 1) for i in fr}) if count else []

            def place(
                n: int,
                name: str,
                cid: str = cid,
                clip: Path = clip,
                fps: float = fps,
                start: float = start,
                real: bool = real,
                boxes: dict = boxes,
                root: str = root,
            ) -> bool:
                return _place(jobs, dropped, n, name, cid, clip, fps, start, real, boxes, root)

            per_rule: dict[str, dict] = {}
            model = clamp(pick3(model_frames(record, csha, item)))
            for r in pred.get("rulings") or []:
                own = clamp(pick3(r.get("frames") or []))
                if own:
                    fr, src = own, "ruling"
                elif model:
                    fr, src = model, "model"
                else:
                    fr, src = clamp(EMPTY_FRAMES), "window"
                shown = [n for n in fr if place(n, str(n))]
                per_rule[r["rule"]] = {
                    "frames": shown,
                    "frames_source": src,
                    "dropped": [n for n in fr if n not in shown],
                }
            rulings[f"{root}/{cid}"] = per_rule

            if cid not in posters_done:
                mid = count // 2
                cands = sorted(range(count), key=lambda n: (abs(n - mid), n)) if real else [mid]
                for n in cands:
                    if not real or boxes_for(boxes, n)[0] is not None:
                        if place(n, "poster"):
                            posters_done.add(cid)
                        break

    # the shift: one poster per window, at the window's middle frame
    shift_dir = ((sources.get("shift") or {}).get("output") or {}).get("path")
    wfile = Path(shift_dir) / "windows.jsonl" if shift_dir else None
    if wfile is not None and wfile.is_file():
        for line in wfile.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            w = json.loads(line)
            wid = w["window"]
            if only and wid not in only:
                continue
            clip = index.find(w["clip_sha256"], w.get("clip"))
            if clip is None:
                missing.append(f"shift/{wid}")
                continue
            dur, fps = probe(clip)
            start, end = float(w.get("start_s", 0.0)), float(w.get("end_s", 0.0))
            count = max(1, int(round((min(end, dur or end) - start) * FRAME_RATE)))
            _place(jobs, dropped, count // 2, "poster", wid, clip, fps, start, False, {}, "shift")

    _clean(out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    def run(file: str) -> None:
        j = jobs[file]
        cut(j["clip"], j["t"], j["fps"], out / file, j["regions"])

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(run, sorted(jobs)))

    frames, blurred = [], []
    for file in sorted(jobs):
        meta = jobs[file]["meta"]
        sha = sha256_file(out / file)
        row = {
            "file": f"frames/{file}",
            "sha256": sha,
            **{
                k: meta[k]
                for k in ("clip", "frame", "at_frame", "t_s", "kind", "blurred")
                if k in meta
            },
        }
        frames.append(row)
        if meta["kind"] == "real":
            blurred.append(
                {
                    "file": f"frames/{file}",
                    "clip": meta["clip"],
                    "frame": meta["frame"],
                    "sha256": sha,
                    "box_frame": meta["box_frame"],
                    "boxes": meta["boxes"],
                    "regions": meta["regions"],
                    "checked": False,
                }
            )
    dropped_u = sorted({json.dumps(d, sort_keys=True) for d in dropped})
    _write_json(
        out / "frames.json",
        {
            "schema": 1,
            "width": OUT_W,
            "frames": frames,
            "rulings": rulings,
            "missing_clips": sorted(missing),
        },
    )
    if blurred or dropped_u:
        _write_json(
            out / "blurred.json",
            {
                "schema": 1,
                "method": BLUR_METHOD,
                "frames": blurred,
                "dropped": [json.loads(d) for d in dropped_u],
            },
        )
    return {
        "frames": len(frames),
        "real": len(blurred),
        "dropped": len(dropped_u),
        "missing": sorted(missing),
        "seconds": round(time.monotonic() - t0, 1),
        "bytes": sum((out / f).stat().st_size for f in jobs),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--clip", action="append", help="only this clip id (repeatable)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg and ffprobe are needed on PATH", file=sys.stderr)
        return 2
    res = build(a.sources, a.out, set(a.clip) if a.clip else None, a.workers)
    print(json.dumps(res, indent=1, sort_keys=True))
    return 1 if res["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
