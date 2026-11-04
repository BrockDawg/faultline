"""Rank possible incident moments from SAM car tracks for steward review.

These are visual search hints, never contact findings or verdicts. The racing SAM experiment
showed that selecting the two largest whole-frame tracks can follow the wrong view, so this
module considers every sufficiently persistent track pair and returns no candidate when the
tracks do not support a close approach followed by a sudden relative-motion change.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from faultline.adapters.video import video

NEAR_PX = 12  # same mask-adjacency threshold used by the 58-clip SAM experiment
TREND_FRAMES = 6


def _box_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    al, at, ar, ab = a
    bl, bt, br, bb = b
    return max(0, al - br, bl - ar, at - bb, bt - ab)


def _dilate(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1)
    h, w = mask.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(3):
        for x in range(3):
            out |= padded[y : y + h, x : x + w]
    return out


def _mask_gap(
    a: tuple[int, int, np.ndarray], b: tuple[int, int, np.ndarray], limit: int
) -> int | None:
    """Exact Chebyshev distance up to `limit`, with work restricted to nearby mask crops."""
    ay, ax, am = a
    by, bx, bm = b
    abox = (ax, ay, ax + am.shape[1] - 1, ay + am.shape[0] - 1)
    bbox = (bx, by, bx + bm.shape[1] - 1, by + bm.shape[0] - 1)
    if _box_gap(abox, bbox) > limit:
        return None
    y0, x0 = min(ay, by) - limit, min(ax, bx) - limit
    y1 = max(ay + am.shape[0], by + bm.shape[0]) + limit
    x1 = max(ax + am.shape[1], bx + bm.shape[1]) + limit
    aa = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    bb = np.zeros_like(aa)
    aa[ay - y0 : ay - y0 + am.shape[0], ax - x0 : ax - x0 + am.shape[1]] = am
    bb[by - y0 : by - y0 + bm.shape[0], bx - x0 : bx - x0 + bm.shape[1]] = bm
    if np.any(aa & bb):
        return 0
    grown = aa
    for radius in range(1, limit + 1):
        grown = _dilate(grown)
        if np.any(grown & bb):
            return radius
    return None


def rank_moments(
    tracks: Mapping[str, Mapping[int, Mapping[str, Any]]],
    masks: Mapping[str, Mapping[int, tuple[int, int, np.ndarray]]],
    *,
    frame_count: int,
    fps: int = video.FPS,
    near_px: int = NEAR_PX,
    trend_frames: int = TREND_FRAMES,
    frame_radius_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Return ranked close-approach / motion-change moments and the frames around each.

    A candidate requires persistent tracks, masks within `near_px`, and the pair's centroid
    distance to shrink before and grow after the closest frame. This ranks where a steward should
    look; occlusion, camera motion and SAM track errors can all create false candidates.
    """
    ids = sorted(set(tracks) & set(masks), key=str)
    radius = max(1, int(round(frame_radius_s * fps)))
    raw: list[dict[str, Any]] = []
    for i, aid in enumerate(ids):
        for bid in ids[i + 1 :]:
            a, b = tracks[aid], tracks[bid]
            common = sorted(set(a) & set(b) & set(masks[aid]) & set(masks[bid]))
            if len(common) < trend_frames * 2 + 1:
                continue
            obs: dict[int, tuple[float, float, float, int]] = {}
            for f in common:
                ac, bc = a[f], b[f]
                obs[f] = (
                    float(ac["cx"]) - float(bc["cx"]),
                    float(ac["cy"]) - float(bc["cy"]),
                    float(ac["area"]) + float(bc["area"]),
                    _mask_gap(masks[aid][f], masks[bid][f], near_px),
                )
            for f in common:
                if obs[f][3] is None:
                    continue
                before = list(range(f - trend_frames, f))
                after = list(range(f + 1, f + trend_frames + 1))
                if not all(x in obs for x in before + after):
                    continue
                d0 = math.hypot(*obs[f][:2])
                db = [math.hypot(*obs[x][:2]) for x in before]
                da = [math.hypot(*obs[x][:2]) for x in after]
                pre = float(np.median(db))
                post = float(np.median(da))
                approach, separation = pre - d0, post - d0
                if approach < 3.0 or separation < 3.0:
                    continue
                # Relative motion cancels much of the camera pan that corrupted single-car
                # displacement scores in the quick mask inspection.
                r_before = np.mean([obs[x][:2] for x in range(f - trend_frames, f - 1)], axis=0)
                r_after = np.mean([obs[x][:2] for x in range(f + 2, f + trend_frames + 1)], axis=0)
                change = float(np.linalg.norm(r_after - r_before))
                gap = int(obs[f][3])
                score = (approach + separation) * (1.0 + (near_px - gap) / near_px) + change
                start = max(0, f - radius)
                end = min(frame_count - 1, f + radius)
                raw.append(
                    {
                        "frame": f,
                        "clip_time_s": round(f / fps, 3),
                        "score": round(score, 3),
                        "mask_gap_px": gap,
                        "pre_distance_px": round(pre, 1),
                        "distance_at_candidate_px": round(d0, 1),
                        "post_distance_px": round(post, 1),
                        "relative_motion_change_px": round(change, 1),
                        "track_pair": [str(aid), str(bid)],
                        "review_frame_range": [start, end],
                        "review_frame_times_s": [
                            round(x / fps, 3) for x in range(start, end + 1, max(1, fps // 4))
                        ],
                    }
                )
    raw.sort(key=lambda x: (-x["score"], x["frame"]))
    picked: list[dict[str, Any]] = []
    for item in raw:
        if any(abs(item["frame"] - prior["frame"]) <= fps // 2 for prior in picked):
            continue
        picked.append(item)
        if len(picked) == 10:
            break
    return picked
