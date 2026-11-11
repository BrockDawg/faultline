"""Perception: SAM 3.1 sees the truck and the people; the replies are the record and are never
re-asked.

For one clip window the record holds, under record/clips/<clip sha256>/:
  encode.mp4.sha256         the 12 fps encode SAM saw (its bytes are rebuilt from the clip; the hash
  pins them) truck_box.txt             SAM image reply, "forklift" on the first frame that shows one
  truck_box.json            {prompt_frame, box, conf} picked from it, deterministically
  truck_track.txt           SAM video reply, box prompt person_track.txt          SAM video reply,
  text prompt "person" masks/<sha>.npz           decoded masks of each reply (a pure function of the
  reply text)
A reply recorded by smoke G (28 Oct 2026) for the same clip is reused as is, under its own hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from faultline.adapters.video import client, sam, video

REPO = (
    Path(__file__).resolve().parents[4]
)  # the repo root: src/faultline/adapters/video/ is four down
ASSETS = Path(__file__).resolve().parent / "data"  # the judge's own data ships inside the adapter
PACKS = REPO / "packs"  # the rules packs live at the repo root
RECORD = Path(os.environ.get("FAULTLINE_RECORD", str(REPO / "record")))
MAX_BOX_STEPS = 5  # first frame with a forklift box: frame 0, then one second at a time


def clip_sha(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clip_dir(csha: str) -> Path:
    return RECORD / "clips" / csha


def _smoke_g(csha: str) -> Path | None:
    stems = json.loads(
        (ASSETS / "perception" / "smoke-g" / "stems.json").read_text(encoding="utf-8")
    )
    for stem, s in stems.items():
        if s == csha and (ASSETS / "perception" / "smoke-g" / stem / "track_raw.txt").exists():
            return ASSETS / "perception" / "smoke-g" / stem
    return None


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def box_prompt(frame: int, box: tuple[int, int, int, int]) -> str:
    left, t, r, b = box
    return (
        f"<{frame}f>1<|box;x1={left};y1={t};x2={min(r, video.W - 1)};y2={min(b, video.H - 1)};w="
        f"{video.W};h={video.H}|>"
    )


class Perception:
    """Everything SAM saw for one clip window, from the record where it exists, from the proxy once
    where it does not.
    """

    def __init__(
        self,
        clip: str | Path | None,
        start_s: float,
        end_s: float,
        csha: str | None = None,
        allow_calls: bool = True,
        allow_decode: bool = True,
    ):
        self.clip, self.start_s, self.end_s = (
            (Path(clip) if clip else None),
            float(start_s),
            float(end_s),
        )
        self.allow_decode = allow_decode and self.clip is not None
        self.used: set[Path] = set()
        self._tm: dict | None = None
        self._pm: dict | None = None
        self._pix: dict | None = None
        self.csha = csha or clip_sha(clip)
        self.dir = clip_dir(self.csha)
        self.allow_calls = allow_calls
        self.notes: list[str] = []
        self._enc: bytes | None = None
        self._rgb: np.ndarray | None = None

    # ---------- the frames
    def rgb(self) -> np.ndarray:
        if self._rgb is None:
            if not self.allow_decode:
                raise client.ApiError(
                    "frames are not decoded in replay and no pixel facts are recorded for "
                    "this window"
                )
            self._rgb = video.decode(self.clip, self.start_s, self.end_s, fps=video.FPS)
        return self._rgb

    def grey(self) -> np.ndarray:
        # frame by frame: the same integer arithmetic as the whole-array form, without a uint16 copy
        # of every frame at once (this host refused the 316 MiB allocation under load)
        src = self.rgb()
        out = np.empty(src.shape[:3], np.uint8)
        for i in range(len(src)):
            f = src[i].astype(np.uint16)
            out[i] = ((f[..., 0] * 299 + f[..., 1] * 587 + f[..., 2] * 114) // 1000).astype(
                np.uint8
            )
        return out

    def encode(self) -> bytes:
        if self._enc is None:
            tmp = self.dir / "encode.mp4"
            self._enc = video.encode_for_sam(self.clip, self.start_s, self.end_s, tmp)
            _write(self.dir / "encode.mp4.sha256", hashlib.sha256(self._enc).hexdigest() + "\n")
            tmp.unlink(
                missing_ok=True
            )  # the bytes are rebuilt from the clip; only the hash is kept
        return self._enc

    # ---------- the replies
    def _reply(self, name: str, make) -> str | None:
        p = self.dir / name
        if p.exists():
            return p.read_text(encoding="utf-8")
        g = _smoke_g(self.csha)
        if g is not None:
            src = {"truck_track.txt": "track_raw.txt", "truck_box.txt": "boxes_raw.txt"}.get(name)
            if src and (g / src).exists():
                text = (g / src).read_text(encoding="utf-8")
                _write(p, text)
                if name == "truck_box.txt":
                    pf = (
                        int((g / "prompt_frame.txt").read_text().strip())
                        if (g / "prompt_frame.txt").exists()
                        else 0
                    )
                    boxes = sam.image_boxes(text)
                    _write(
                        self.dir / "truck_box.json",
                        json.dumps(
                            {
                                "prompt_frame": pf,
                                "box": boxes[0]["box"] if boxes else None,
                                "conf": boxes[0]["conf"] if boxes else None,
                                "source": "smoke-g",
                            }
                        )
                        + "\n",
                    )
                self.notes.append(f"{name}: smoke G's recorded reply")
                return text
        if not self.allow_calls:
            return None
        text = make()
        if text is not None:
            _write(p, text)
        return text

    def truck_box(self) -> dict | None:
        """{prompt_frame, box, conf} or None when no frame shows a forklift."""
        pj = self.dir / "truck_box.json"
        if pj.exists():
            d = json.loads(pj.read_text(encoding="utf-8"))
            return d if d.get("box") else None
        if not self.allow_calls:
            return None
        rgb = self.rgb()
        found = None
        for step in range(MAX_BOX_STEPS):
            f = step * video.FPS
            if f >= len(rgb):
                break
            jpeg = video.jpeg_of(rgb[f])
            r = client.sam_image(jpeg, "forklift", tag=f"truck-box:{self.csha[:8]}:{f}")
            _write(self.dir / f"truck_box_f{f}.txt", r["text"])
            boxes = sam.image_boxes(r["text"])
            if boxes:
                found = {
                    "prompt_frame": f,
                    "box": list(boxes[0]["box"]),
                    "conf": boxes[0]["conf"],
                    "source": "sam-3.1 image",
                }
                _write(self.dir / "truck_box.txt", r["text"])
                break
        _write(
            pj,
            json.dumps(
                found
                or {
                    "prompt_frame": None,
                    "box": None,
                    "conf": None,
                    "source": "sam-3.1 image: no forklift box",
                }
            )
            + "\n",
        )
        return found

    def truck_text(self) -> str | None:
        def make():
            tb = self.truck_box()
            if tb is None:
                return None
            r = client.sam_video(
                self.encode(),
                box_prompt(tb["prompt_frame"], tuple(tb["box"])),
                tag=f"truck:{self.csha[:8]}",
            )
            return r["text"]

        return self._reply("truck_track.txt", make)

    def person_text(self) -> str | None:
        def make():
            r = client.sam_video(self.encode(), "person", tag=f"person:{self.csha[:8]}")
            self._write_person_run(r, r["text"], "first ask")
            return r["text"]

        return self._reply("person_track.txt", make)

    # ---------- ruling 1: did the person detector run on every frame of the window?
    def _write_person_run(self, r: dict, text: str, how: str) -> None:
        u = r.get("usage") or {}
        _write(
            self.dir / "person_run.json",
            json.dumps(
                {
                    "window": [f"{self.start_s:.3f}", f"{self.end_s:.3f}"],
                    "frames_processed": int(u.get("video_frames_processed") or 0),
                    "reply_sha256": sam.sha(text),
                    "how": how,
                },
                sort_keys=True,
            )
            + chr(10),
        )

    def person_run(self) -> dict | None:
        """{window, frames_processed, reply_sha256, how}: SAM's own count of the frames the "person"
        video read processed, kept beside its reply (ruling 1). A reply recorded before this file
        existed is asked once more with the identical request (the proxy's cache serves it at no
        cost) only to read that count; the count is kept only when the reply is byte-identical to
        the recorded one. None when it is not recorded and cannot be asked: the detector's run is
        then unproven, and a person rule stays "unable to rule"."""
        p = self.dir / "person_run.json"
        if p.exists():
            self.used.add(p)
            return json.loads(p.read_text(encoding="utf-8"))
        text = self.person_text()
        if p.exists():
            self.used.add(p)
            return json.loads(p.read_text(encoding="utf-8"))
        if text is None or not self.allow_calls:
            return None
        hp = self.dir / "encode.mp4.sha256"
        before = hp.read_text(encoding="utf-8") if hp.exists() else None
        enc = self.encode()
        if before is not None and before.strip() != hashlib.sha256(enc).hexdigest():
            _write(
                hp, before
            )  # the recorded encode hash stays; a different encode is not the request SAM saw
            self.notes.append(
                "person_run: this host's encode differs from the recorded one; the frame "
                "count is not asked"
            )
            return None
        r = client.sam_video(enc, "person", tag=f"person-count:{self.csha[:8]}")
        if r["text"] != text:
            self.notes.append(
                "person_run: the re-asked person read differs from the recorded one; its "
                "frame count is not kept"
            )
            return None
        self._write_person_run(
            r, text, "re-asked once for the frame count; reply identical to the recorded one"
        )
        self.used.add(p)
        return json.loads(p.read_text(encoding="utf-8"))

    def trucks_all_text(self) -> str | None:
        def make():
            r = client.sam_video(self.encode(), "forklift", tag=f"trucks-all:{self.csha[:8]}")
            return r["text"]

        return self._reply("trucks_all.txt", make)

    def text_track(self, name: str, prompt: str) -> str | None:
        """A SAM 3.1 video track on a text prompt (the fork and mast reads), asked once, kept as
        record/clips/<sha>/<name>.txt.
        """

        def make():
            r = client.sam_video(self.encode(), prompt, tag=f"{name}:{self.csha[:8]}")
            return r["text"]

        return self._reply(f"{name}.txt", make)

    def text_masks(self, name: str, prompt: str) -> dict[str, dict[int, np.ndarray]]:
        """{object_id: {frame: mask}} of a text-prompted track, from the record."""
        text = self.text_track(name, prompt)
        if not text:
            return {}
        out: dict[str, dict[int, np.ndarray]] = {}
        for f, d in self._masks(text).items():
            for oid, e in d.items():
                if e["mask"].any():
                    out.setdefault(oid, {})[f] = e["mask"]
        return out

    def track_stats(self, name: str, prompt: str) -> dict[str, dict[int, dict]]:
        """Per-object, per-frame mask statistics of a text-prompted track (sam.track_stats), from
        the record.
        """
        text = self.text_track(name, prompt)
        if not text:
            return {}
        self.used.add(self.dir / "masks" / f"{sam.sha(text)}.npz")
        return sam.track_stats(text, self.dir / "masks")

    # ---------- the load reads: one SAM 3.1 video track per measure.LOAD_PROMPTS text,
    # kept under contact/load_run<r>.txt with its decoded masks beside the other replies' as packed
    # bits
    def load_text_run(self, run: int) -> str | None:
        from faultline.adapters.video import measure

        def make():
            r = client.sam_video(
                self.encode(), measure.LOAD_PROMPTS[run], tag=f"load-run{run}:{self.csha[:8]}"
            )
            return r["text"]

        text = self._reply(f"contact/load_run{run}.txt", make)
        if text is not None:
            self.used.add(self.dir / "contact" / f"load_run{run}.txt")
        return text

    def load_masks_run(self, run: int) -> dict[str, dict[int, tuple]]:
        """{object_id: {frame: (y0, x0, cropped mask)}} for one load prompt (cut to each mask's box,
        so a read with many objects is never held as full frames; measure.load_drops reads the same
        pixels)."""
        text = self.load_text_run(run)
        if not text:
            return {}
        self.used.add(self.dir / "masks" / f"{sam.sha(text)}.npz")
        return sam.mask_crops(text, self.dir / "masks")

    # ---------- the empty-window read (ruling 1 of 30 Oct): a SAM 3.1 video text track over this
    # window's
    # own encode, kept with the frame count SAM reports having processed, so "nobody on any frame"
    # is a recorded fact
    def empty_track(self, name: str, prompt: str) -> tuple[str | None, dict | None]:
        """(reply text, {prompt, video_frames_processed}) for one text prompt on this window, from
        the record where it exists.
        """
        d = self.dir / "empty" / f"{self.start_s:.3f}_{self.end_s:.3f}"
        pt, pj = d / f"{name}.txt", d / f"{name}.json"
        if pt.exists() and pj.exists():
            self.used.update((pt, pj))
            return pt.read_text(encoding="utf-8"), json.loads(pj.read_text(encoding="utf-8"))
        if not self.allow_calls:
            return None, None
        r = client.sam_video(self.encode(), prompt, tag=f"empty-{name}:{self.csha[:8]}")
        meta = {
            "prompt": prompt,
            "video_frames_processed": int(
                (r.get("usage") or {}).get("video_frames_processed") or 0
            ),
        }
        _write(pt, r["text"])
        _write(pj, json.dumps(meta, sort_keys=True) + chr(10))
        self.used.update((pt, pj))
        return r["text"], meta

    # ---------- the masks
    def _masks(self, text: str) -> dict:
        objs = sam.masks(text, self.dir / "masks")
        self.used.add(self.dir / "masks" / f"{sam.sha(text)}.npz")
        return objs

    def truck_masks(self) -> dict[int, np.ndarray]:
        if self._tm is not None:
            return self._tm
        text = self.truck_text()
        if not text:
            self._tm = {}
            return self._tm
        objs = self._masks(text)
        out = {}
        for f, d in objs.items():
            o = d.get("1") or (d[sorted(d)[0]] if d else None)
            if o is not None:
                out[f] = o["mask"]
        self._tm = out
        return out

    def person_masks(self) -> dict[str, dict[int, dict]]:
        """{object_id: {frame: {mask, box, conf}}}."""
        if self._pm is not None:
            return self._pm
        text = self.person_text()
        if not text:
            self._pm = {}
            return self._pm
        objs = self._masks(text)
        out: dict[str, dict[int, dict]] = {}
        for f, d in objs.items():
            for oid, e in d.items():
                out.setdefault(oid, {})[f] = e
        self._pm = out
        return out

    def extra_trucks(self) -> list[dict]:
        """Every truck SAM's "forklift" text track found other than the box-prompted one, as {boxes,
        masks}.

        Asked only for a clip with a person track (the operator rule is its only reader). An object
        whose mask overlaps the box-prompted truck (IoU at least 0.3 on half the frames both hold)
        is that truck and is left out.
        """
        if not self.person_masks():
            return []
        text = self.trucks_all_text()
        if not text:
            return []
        main = self.truck_masks()
        objs = self._masks(text)
        per: dict[str, dict[int, np.ndarray]] = {}
        for f, d in objs.items():
            for oid, e in d.items():
                if e["mask"].any():
                    per.setdefault(oid, {})[f] = e["mask"]
        out = []
        for oid in sorted(per, key=lambda k: int(k) if k.isdigit() else 0):
            ms = per[oid]
            if len(ms) < 6:
                continue
            both = [f for f in ms if f in main and main[f].any()]
            same = 0
            for f in both:
                a, b = ms[f], main[f]
                inter = int((a & b).sum())
                uni = int((a | b).sum())
                same += uni > 0 and inter / uni >= 0.3
            if both and same >= 0.5 * len(both):
                continue
            out.append(
                {"boxes": {f: sam.box_of(m) for f, m in ms.items()}, "masks": ms, "sam_id": oid}
            )
        return out

    # ---------- the gate facts (reads, kept like the pixel facts so a replay never decodes)
    def gate_facts(self, key: dict, make) -> dict:
        """The recorded pre-model gate reads for this window; measured (and written) only when
        absent and frames decode.
        """
        from faultline.adapters.video import record

        p = self.dir / "gates" / f"{record.sha_text(record.canon(key))}.json"
        if p.exists():
            facts = json.loads(p.read_text(encoding="utf-8"))
        else:
            if not self.allow_decode:
                raise client.ApiError(
                    "frames are not decoded in replay and no gate facts are recorded for "
                    "this window"
                )
            facts = json.loads(record.canon(make(self.grey())))
            _write(p, json.dumps(facts, indent=1, sort_keys=True, ensure_ascii=True) + chr(10))
        self.used.add(p)
        return facts

    # ---------- the pixel facts
    def pixels_key(self, marks: dict) -> str:
        from faultline.adapters.video import record

        tt, pt = self.truck_text(), self.person_text()
        return record.sha_text(
            record.canon(
                {
                    "window": [f"{self.start_s:.3f}", f"{self.end_s:.3f}"],
                    "truck": sam.sha(tt) if tt else None,
                    "person": sam.sha(pt) if pt else None,
                    "marks": record.canon(marks),
                    "constants": record.constants(),
                }
            )
        )

    def pixels(self, marks: dict) -> dict:
        """The recorded pixel facts for this window; measured (and written) only when absent and
        frames can be decoded.
        """
        if self._pix is not None:
            return self._pix
        from faultline.adapters.video import measure, record

        p = self.dir / "pixels" / f"{self.pixels_key(marks)}.json"
        if p.exists():
            self._pix = json.loads(p.read_text(encoding="utf-8"))
        else:
            rgb = self.rgb()
            grey = self.grey()
            facts = measure.pixel_facts(grey, rgb, self.truck_masks(), self.person_masks(), marks)
            facts = json.loads(record.canon(facts))
            _write(p, json.dumps(facts, indent=1, sort_keys=True, ensure_ascii=True) + chr(10))
            self._pix = facts
            self._rgb = None
        self.used.add(p)
        return self._pix

    def inputs(self) -> dict[str, str]:
        """The perception files this ruling used and their sha256, for the ruling's record.

        Names are posix paths relative to the record root. The clip's replies (every top-level file)
        are named whole; of the masks and pixel facts only the ones this window read. Text is hashed
        LF-normalised, masks raw.
        """
        from faultline.adapters.video import record

        files = (
            {
                p
                for p in self.dir.iterdir()
                if p.is_file() and p.suffix != ".mp4" and not p.name.endswith(".tmp")
            }
            if self.dir.is_dir()
            else set()
        )
        files |= {p for p in self.used if p.is_file()}
        out = {}
        for p in sorted(files, key=lambda q: q.relative_to(RECORD).as_posix()):
            out[p.relative_to(RECORD).as_posix()] = record.sha_norm(p)
        if self._pix is not None:
            out["frames"] = self._pix["frames_sha256"]
        return out
