"""SAM 3.1 replies: parse, decode, cache. The reply text is the record; decoded masks are a pure
function of it.

SAM is not deterministic on identical bytes, so a ruling never calls SAM twice for one clip: the
first reply is written under the record and every later run (and every replay) reads it back.
Decoding a reply takes about a minute in pure Python, so the decoded masks are cached as packed bits
beside it, keyed by the reply's sha256.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from faultline.adapters.video.video import H, W


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def image_boxes(text: str) -> list[dict]:
    """Boxes of an image reply: [{box: (l, t, r, b), conf}] sorted by confidence then area, best
    first.
    """
    import meta_sam_parser as m

    p = m.image_segmentation_format().create_parser()
    list(p.push(text))
    recs = [r for r in p.finish(m.CompletedOutcome()).result.records if r.kind == "box"]
    out = [
        {
            "box": (int(r.left), int(r.top), int(r.right), int(r.bottom)),
            "conf": float(r.confidence or 0.0),
        }
        for r in recs
    ]
    return sorted(
        out,
        key=lambda r: (r["conf"], (r["box"][2] - r["box"][0]) * (r["box"][3] - r["box"][1])),
        reverse=True,
    )


def _parse_video(text: str) -> dict[int, dict[str, dict]]:
    import meta_sam_parser as m

    p = m.video_segmentation_format().create_parser()
    list(p.push(text))
    out: dict[int, dict[str, dict]] = {}
    for rec in p.finish(m.CompletedOutcome()).result.records:
        oid = str(rec.object_id)
        if rec.kind == "box":
            out.setdefault(int(rec.frame.frame_index), {}).setdefault(oid, {}).update(
                box=(int(rec.left), int(rec.top), int(rec.right), int(rec.bottom)),
                conf=float(rec.confidence or 0.0),
            )
        elif rec.kind == "mask":
            e = out.setdefault(int(rec.frame.frame_index), {}).setdefault(oid, {})
            e.setdefault("conf", float(rec.confidence or 0.0))
            e.setdefault(
                "box",
                (
                    int(rec.bounds.left),
                    int(rec.bounds.top),
                    int(rec.bounds.right),
                    int(rec.bounds.bottom),
                ),
            )
            mk = rec.mask
            ras = (
                np.frombuffer(m.decode_mask_to_raster(mk), dtype=np.uint8)[
                    : mk.width * mk.height
                ].reshape(mk.height, mk.width)
                > 0
            )
            full = np.zeros((H, W), dtype=bool)
            y0, x0 = int(rec.bounds.top), int(rec.bounds.left)
            hh, ww = min(mk.height, H - y0), min(mk.width, W - x0)
            if hh > 0 and ww > 0:
                full[y0 : y0 + hh, x0 : x0 + ww] = ras[:hh, :ww]
            e["mask"] = full
    return out


def masks(text: str, cache_dir: Path) -> dict[int, dict[str, dict]]:
    """{frame: {object_id: {box, conf, mask}}}; the packed-bit cache under cache_dir/<sha>.npz is a
    pure function of text.
    """
    h = sha(text)
    p = cache_dir / f"{h}.npz"
    if p.exists():
        z = np.load(p)
        out: dict[int, dict[str, dict]] = {}
        for k in z.files:
            if not k.startswith("m_"):
                continue
            _, f, oid = k.split("_", 2)
            m = np.unpackbits(z[k])[: H * W].reshape(H, W).astype(bool)
            box = tuple(int(v) for v in z[f"b_{f}_{oid}"])
            conf = float(z[f"c_{f}_{oid}"])
            out.setdefault(int(f), {})[oid] = {"box": box, "conf": conf, "mask": m}
        return out
    out = _parse_video(text)
    arrs: dict[str, np.ndarray] = {}
    for f, objs in out.items():
        for oid, e in objs.items():
            if e.get("mask") is None or not e["mask"].any():
                continue
            arrs[f"m_{f}_{oid}"] = np.packbits(e["mask"].ravel())
            arrs[f"b_{f}_{oid}"] = np.asarray(e["box"], dtype=np.int32)
            arrs[f"c_{f}_{oid}"] = np.asarray(e["conf"], dtype=np.float64)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **arrs)
    tmp.replace(p)
    return {
        f: {oid: e for oid, e in objs.items() if e.get("mask") is not None and e["mask"].any()}
        for f, objs in out.items()
    }


def crop(m: np.ndarray) -> tuple[int, int, np.ndarray] | None:
    """A full-frame mask as (y0, x0, the mask cut to its own bounding box); None when empty."""
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return None
    y0, x0 = int(ys.min()), int(xs.min())
    return y0, x0, m[y0 : int(ys.max()) + 1, x0 : int(xs.max()) + 1].copy()


def mask_crops(text: str, cache_dir: Path) -> dict[str, dict[int, tuple[int, int, np.ndarray]]]:
    """{object_id: {frame: (y0, x0, cropped mask)}} of a video reply, one full mask unpacked at a
    time.

    The same pixels masks() returns, cut to each mask's bounding box: a load read with many objects
    is never held as full frames (peak commit 1.6 GB to 0.79 GB on two clips). The packed-bit cache
    is written by masks() first."""
    h = sha(text)
    p = cache_dir / f"{h}.npz"
    if not p.exists():
        masks(text, cache_dir)
    out: dict[str, dict[int, tuple[int, int, np.ndarray]]] = {}
    z = np.load(p)
    for k in z.files:
        if not k.startswith("m_"):
            continue
        _, f, oid = k.split("_", 2)
        c = crop(np.unpackbits(z[k])[: H * W].reshape(H, W).astype(bool))
        if c is not None:
            out.setdefault(oid, {})[int(f)] = c
    return out


def track_stats(text: str, cache_dir: Path) -> dict[str, dict[int, dict]]:
    """{object_id: {frame: {cx, cy, area, box, mask_packed}}} of a video reply, one mask in memory
    at a time.

    The decoded masks are kept as packed bits under cache_dir/<sha>.npz exactly as masks() keeps
    them (a pure function of the reply text); a reply with many objects (a "cardboard box" track) is
    never held unpacked whole.
    """
    h = sha(text)
    p = cache_dir / f"{h}.npz"
    out: dict[str, dict[int, dict]] = {}

    def add(f: int, oid: str, m: np.ndarray, packed: np.ndarray) -> None:
        ys, xs = np.nonzero(m)
        if len(ys) == 0:
            return
        out.setdefault(oid, {})[f] = {
            "cx": float(xs.mean()),
            "cy": float(ys.mean()),
            "area": int(len(ys)),
            "box": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            "packed": packed,
        }

    if p.exists():
        z = np.load(p)
        for k in z.files:
            if k.startswith("m_"):
                _, f, oid = k.split("_", 2)
                packed = z[k]
                add(int(f), oid, np.unpackbits(packed)[: H * W].reshape(H, W).astype(bool), packed)
        return out
    import meta_sam_parser as msp

    parser = msp.video_segmentation_format().create_parser()
    list(parser.push(text))
    arrs: dict[str, np.ndarray] = {}
    meta: dict[tuple[int, str], dict] = {}
    for rec in parser.finish(msp.CompletedOutcome()).result.records:
        oid, f = str(rec.object_id), int(rec.frame.frame_index)
        if rec.kind == "box":
            meta.setdefault((f, oid), {}).update(
                box=(int(rec.left), int(rec.top), int(rec.right), int(rec.bottom)),
                conf=float(rec.confidence or 0.0),
            )
        elif rec.kind == "mask":
            e = meta.setdefault((f, oid), {})
            e.setdefault("conf", float(rec.confidence or 0.0))
            e.setdefault(
                "box",
                (
                    int(rec.bounds.left),
                    int(rec.bounds.top),
                    int(rec.bounds.right),
                    int(rec.bounds.bottom),
                ),
            )
            mk = rec.mask
            ras = (
                np.frombuffer(msp.decode_mask_to_raster(mk), dtype=np.uint8)[
                    : mk.width * mk.height
                ].reshape(mk.height, mk.width)
                > 0
            )
            full = np.zeros((H, W), dtype=bool)
            y0, x0 = int(rec.bounds.top), int(rec.bounds.left)
            hh, ww = min(mk.height, H - y0), min(mk.width, W - x0)
            if hh > 0 and ww > 0:
                full[y0 : y0 + hh, x0 : x0 + ww] = ras[:hh, :ww]
            if not full.any():
                continue
            packed = np.packbits(full.ravel())
            arrs[f"m_{f}_{oid}"] = packed
            arrs[f"b_{f}_{oid}"] = np.asarray(e["box"], dtype=np.int32)
            arrs[f"c_{f}_{oid}"] = np.asarray(e["conf"], dtype=np.float64)
            add(f, oid, full, packed)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **arrs)
    tmp.replace(p)
    return out


# ---------------- mask geometry (smoke I's footpoint and envelope, unchanged)
def foot(mask: np.ndarray) -> tuple[float, float] | None:
    ys = np.where(mask.any(axis=1))[0]
    if len(ys) == 0:
        return None
    top, bot = int(ys[0]), int(ys[-1])
    n = max(3, int(np.ceil(0.03 * (bot - top + 1))))
    xs = np.where(mask[max(top, bot - n + 1) : bot + 1].any(axis=0))[0]
    return (float(xs.mean()), float(bot))


def top_point(mask: np.ndarray) -> tuple[float, float] | None:
    """The mask's top point: the mean column of its top rows (3 rows or 3% of its height) and its
    top row; None when the mask touches the frame's top edge (the frame cuts it there too). the far
    end of a truck whose bottom is cut by the frame, read where the footpoint cannot be."""
    ys = np.where(mask.any(axis=1))[0]
    if len(ys) == 0:
        return None
    top, bot = int(ys[0]), int(ys[-1])
    if top <= 1:
        return None
    n = max(3, int(np.ceil(0.03 * (bot - top + 1))))
    xs = np.where(mask[top : min(bot, top + n - 1) + 1].any(axis=0))[0]
    return (float(xs.mean()), float(top))


def envelope(mask: np.ndarray, step: int = 2) -> np.ndarray:
    """Bottom envelope: (x, lowest row) for every `step`th column the mask covers."""
    cols = np.where(mask.any(axis=0))[0][::step]
    if len(cols) == 0:
        return np.zeros((0, 2))
    flipped = mask[::-1, cols]
    low = mask.shape[0] - 1 - np.argmax(flipped, axis=0)
    return np.c_[cols.astype(float), low.astype(float)]


def box_of(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    return (int(xs[0]), int(ys[0]), int(xs[-1]), int(ys[-1]))


def dilate(mask: np.ndarray, px: int) -> np.ndarray:
    """Chessboard dilation by px (px iterations of a 3x3 max), numpy only."""
    m = mask.copy()
    for _ in range(px):
        d = m.copy()
        d[1:, :] |= m[:-1, :]
        d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        d[1:, 1:] |= m[:-1, :-1]
        d[1:, :-1] |= m[:-1, 1:]
        d[:-1, 1:] |= m[1:, :-1]
        d[:-1, :-1] |= m[1:, 1:]
        m = d
    return m


def chessboard_to(mask: np.ndarray, limit: int) -> np.ndarray:
    """Chessboard distance to the nearest True pixel, 0 inside, capped at limit + 1."""
    dist = np.full(mask.shape, limit + 1, dtype=np.int16)
    cur = mask.copy()
    dist[cur] = 0
    for k in range(1, limit + 1):
        nxt = dilate(cur, 1)
        ring = nxt & ~cur
        dist[ring] = k
        cur = nxt
        if cur.all():
            break
    return dist


def frames_with_objects(text: str) -> dict[int, int]:
    """{frame: number of objects} of a video reply, from its box and mask records, without decoding
    a mask ( empty-window read: an empty reply, or one with no record, holds no object on any
    frame)."""
    if not text or not text.strip():
        return {}
    import meta_sam_parser as m

    p = m.video_segmentation_format().create_parser()
    list(p.push(text))
    seen: dict[int, set] = {}
    for rec in p.finish(m.CompletedOutcome()).result.records:
        if rec.kind in ("box", "mask"):
            seen.setdefault(int(rec.frame.frame_index), set()).add(str(rec.object_id))
    return {f: len(v) for f, v in sorted(seen.items())}
