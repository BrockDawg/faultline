"""The operator rule (design): a person seated on a truck is its driver, not a pedestrian.

A person track is the truck's driver only when three reads agree on the frames it shares with a
truck track:
  seat     the person's lowest pixel sits inside the truck's own silhouette and above the truck's
  lowest pixel by at
           least SEAT_LIFT truck heights: the feet are on the truck, not on the floor in front of
           it;
  inside   the person's box centre sits inside the truck's box; ride     the person's box centre
  keeps the same place relative to the truck box (spread under RIDE_SD truck widths
           across and RIDE_SD_Y truck heights down): the person rides with the truck rather than
           walking past it.
Each read must hold on at least SHARE of the shared frames, and the track must share at least
MIN_SHARED frames.
The old rule (box centre inside the truck box alone) dropped a walker crossing in front of a truck
facing the camera; that walker's feet are on the floor below the truck's lowest pixel, so the seat
read keeps them.

A truck seen only by its box (no mask) uses its box as the silhouette. Nothing here calls a model;
the thresholds were fixed from the five hand-labelled drivers and thirteen pedestrians of smoke E
before the twin check was run.
"""

from __future__ import annotations

import numpy as np

SEAT_LIFT = 0.05  # feet at least this many truck heights above the truck's lowest pixel
SHARE = 0.6  # each read must hold on this share of shared frames
RIDE_SD = 0.12  # std of the box-centre offset across, in truck widths
RIDE_SD_Y = 0.15  # std of the box-centre offset down, in truck heights
MIN_SHARED = 6  # half a second at 12 fps


def frame_reads(pbox, tbox, tmask=None) -> dict:
    """The three reads on one frame for one person box against one truck (box, optional mask)."""
    x0, y0, x1, y1 = pbox
    t0, t1, t2, t3 = tbox
    th, tw = max(t3 - t1, 1), max(t2 - t0, 1)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    inside = t0 <= cx <= t2 and t1 <= cy <= t3
    lift = (t3 - y1) / th
    fx, fy = int(round(cx)), int(round(y1))
    if tmask is not None:
        H, W = tmask.shape
        on = 0 <= fx < W and 0 <= fy < H and bool(tmask[fy, fx])
    else:
        on = t0 <= fx <= t2 and t1 <= fy <= t3
    return {
        "inside": inside,
        "seat": bool(on and lift >= SEAT_LIFT),
        "lift": lift,
        "ox": (cx - (t0 + t2) / 2) / tw,
        "oy": (cy - (t1 + t3) / 2) / th,
    }


def classify(person: dict, trucks: list[dict]) -> dict:
    """person: {frame: box}; trucks: [{"boxes": {frame: box}, "masks": {frame: mask} or None}].

    Returns {"operator": bool, "truck": index or None, "shared": n, "seat": share, "inside": share,
    "ride_sd": (sx, sy) or None, "why": text}. A person is the operator of the truck that best
    explains them.
    """
    best = {
        "operator": False,
        "truck": None,
        "shared": 0,
        "seat": 0.0,
        "inside": 0.0,
        "ride_sd": None,
        "why": "never shared a frame with a truck",
    }
    for ti, t in enumerate(trucks):
        rows = []
        for f, pb in person.items():
            tb = t["boxes"].get(f)
            if tb is None:
                continue
            m = (t.get("masks") or {}).get(f)
            rows.append(frame_reads(pb, tb, m))
        if not rows:
            continue
        n = len(rows)
        seat = sum(r["seat"] for r in rows) / n
        inside = sum(r["inside"] for r in rows) / n
        sx = float(np.std([r["ox"] for r in rows]))
        sy = float(np.std([r["oy"] for r in rows]))
        ok = (
            n >= MIN_SHARED
            and seat >= SHARE
            and inside >= SHARE
            and sx <= RIDE_SD
            and sy <= RIDE_SD_Y
        )
        if n < MIN_SHARED:
            why = f"shared only {n} frames with truck {ti}"
        elif ok:
            why = (
                f"seated on truck {ti}: feet on the truck above its floor line on "
                f"{seat:.0%} of {n} shared frames, "
                f"centre in its box on {inside:.0%}, riding with it (spread {sx:.3f} "
                f"widths, {sy:.3f} heights)"
            )
        else:
            fails = [
                w
                for w, bad in (
                    ("seat", seat < SHARE),
                    ("inside", inside < SHARE),
                    ("ride", sx > RIDE_SD or sy > RIDE_SD_Y),
                )
                if bad
            ]
            why = (
                f"on foot against truck {ti}: {', '.join(fails)} read fails (seat {seat:.0%}, "
                f"inside {inside:.0%}, spread {sx:.3f}/{sy:.3f})"
            )
        row = {
            "operator": ok,
            "truck": ti,
            "shared": n,
            "seat": round(seat, 3),
            "inside": round(inside, 3),
            "ride_sd": (round(sx, 4), round(sy, 4)),
            "why": why,
        }
        if ok or (not best["operator"] and n > best["shared"]):
            best = row
            if ok:
                break
    return best
