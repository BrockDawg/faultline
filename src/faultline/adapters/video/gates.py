"""The gates: a script decides whether the window can carry a ruling at all, before any model is
asked, and names the field.

Order, cheapest and widest first; the first gate that fires refuses every rule, naming its field:
  1. window.covers_second  the window (clamped to the clip's own length) is at least one second, and
     decodes to a second of frames
  2. window.one_shot       no shot cut: a hard cut (mean grey change over CUT_HARD) or a spike cut
     (a change CUT_SPIKE times its
                           neighbours and at least CUT_SPIKE_MIN grey levels, which is how a cut
                           between two takes of one camera reads)
  3. camera.static         the camera held: phase correlation of the first and last second within
     CAMERA_HELD_PX
  -- the vision model is asked only past here --
  4. truck.moving          a truck track exists: SAM's forklift box on a frame and at least a second
     of truck masks
  5. camera.static         the camera is a marked one: its clip bytes, or its frames matched to a
     marked camera's reference
                           stills (FP_MATCH correlation over the part of the frame in view); else no
                           floor plane holds
And one per-rule gate, after the fact sheet:
  6. person.in_rear_cone   the truck reversed with no spotter seen, but the rear cone the spotter
     would stand in is mostly out
                           of view (off the frame or cropped to black), so "no spotter" is not
                           proven

Every threshold was fixed on 29 Oct before the second gate set was built, and is part of the
record's constants.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from faultline.adapters.video.video import FPS, H, W

MIN_WINDOW_S = 1.0
CUT_HARD = 40.0  # the base's level: mean absolute grey change of a hard cut
CUT_SPIKE = 2.4  # a change this many times its four neighbours' mean ...
CUT_SPIKE_MIN = 4.0  # ... and at least this many grey levels is a cut between takes
VIEW_LEVEL = (
    8.0  # a pixel whose brightest moment is under this is out of view (cropped to black) ...
)
VIEW_SHARE = 0.9  # ... a 16 px block is dark when under this share of its pixels reach it ...
VIEW_BAND = 0.8  # ... and a block row or column this dark is cropped out of view
FP_STEP = 16  # fingerprint block size: 1280x720 -> 80x45
FP_MATCH = 0.90  # mean correlation of time-aligned reference stills that matches a marked camera
# of the rear cone's floor points inside the camera's frame, the share that must be in view (not
# cropped to black)
CONE_VISIBLE = 0.75
CONE_RADII, CONE_ANGLES = 8, 9

KEYS = [
    "MIN_WINDOW_S",
    "CUT_HARD",
    "CUT_SPIKE",
    "CUT_SPIKE_MIN",
    "VIEW_LEVEL",
    "VIEW_SHARE",
    "VIEW_BAND",
    "FP_STEP",
    "FP_MATCH",
    "CONE_VISIBLE",
    "CONE_RADII",
    "CONE_ANGLES",
]

FIELD_TEXT = {
    "window.covers_second": "The window is {secs:.2f} s long, under the one second every speed, "
    "state and direction "
    "is measured over, so no rule can be ruled.",
    "window.one_shot": "The window holds a shot cut at frame {frame} (grey change {d:.1f}, "
    "{ratio:.1f} times "
    "its neighbours), so one measurement cannot follow the truck across it and no rule is "
    "ruled.",
    "camera.static": "The camera moved; this judge reads fixed site cameras. It moved during the "
    "window (up "
    "to {shift:.1f} px against the first second, held for only {held:.1f} s from the "
    "start), so a floor plane marked for a still camera does not hold and no rule is ruled.",
    "truck.moving": "No truck track exists in this window: {why}. With no truck there is no "
    "motion, "
    "direction, distance or contact to measure, so no rule is ruled.",
    "camera.unmatched": "This camera is not one the site has marked: its frames match no marked "
    "camera's "
    "reference stills (best correlation {best:.2f}, the line is {line:.2f}), so no floor "
    "plane, metre or direction exists and no rule is ruled.",
}


def constants() -> dict:
    return {k: globals()[k] for k in KEYS}


def grey_of(rgb: np.ndarray) -> np.ndarray:
    rgb16 = rgb.astype(np.uint16)
    return ((rgb16[..., 0] * 299 + rgb16[..., 1] * 587 + rgb16[..., 2] * 114) // 1000).astype(
        np.uint8
    )


def blocks(g: np.ndarray, step: int = FP_STEP) -> np.ndarray:
    """Block means of a grey frame (or a stack), float32."""
    g = g.astype(np.float32)
    if g.ndim == 2:
        g = g[None]
    n, h, w = g.shape
    return (
        g[:, : h - h % step, : w - w % step]
        .reshape(n, h // step, step, w // step, step)
        .mean(axis=(2, 4))
    )


# ---------------- 1. window length
def window_seconds(
    start_s: float, end_s: float, clip_duration: float | None, n_frames: int
) -> float:
    end = end_s if clip_duration is None else min(end_s, clip_duration)
    return max(0.0, min(end - start_s, n_frames / FPS))


# ---------------- 2. shot cuts
def shot_cuts(grey: np.ndarray) -> list[dict]:
    """[{frame, d, ratio}] for every cut in the window."""
    if len(grey) < 2:
        return []
    g = grey[:, ::2, ::2].astype(np.int16)
    d = np.array([float(np.abs(g[i] - g[i - 1]).mean()) for i in range(1, len(g))])
    out = []
    for k in range(len(d)):
        nb = [d[j] for j in (k - 2, k - 1, k + 1, k + 2) if 0 <= j < len(d)]
        ratio = float(d[k] / max(float(np.mean(nb)), 0.5)) if nb else 1.0
        if d[k] > CUT_HARD or (ratio >= CUT_SPIKE and d[k] >= CUT_SPIKE_MIN):
            out.append({"frame": k + 1, "d": round(float(d[k]), 2), "ratio": round(ratio, 2)})
    return out


# ---------------- view: the part of the frame that shows the scene
def view_blocks(grey: np.ndarray) -> np.ndarray:
    """bool [45, 80]: the part of the frame that shows the scene. A 16 px block is dark when under
    VIEW_SHARE of its pixels reach VIEW_LEVEL at any moment of the window; a crop to black is a band
    of dark rows or columns (VIEW_BAND of a block row or column dark), so a shadow inside the scene
    stays in view."""
    t = grey.max(axis=0) >= VIEW_LEVEL
    h, w = t.shape
    t = t[: h - h % FP_STEP, : w - w % FP_STEP].reshape(
        h // FP_STEP, FP_STEP, w // FP_STEP, FP_STEP
    )
    dark = t.mean(axis=(1, 3)) < VIEW_SHARE
    rows = dark.mean(axis=1) >= VIEW_BAND
    cols = dark.mean(axis=0) >= VIEW_BAND
    return ~(rows[:, None] | cols[None, :])


def in_view(view: np.ndarray, pts) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    ok = (
        (pts[:, 0] >= 0)
        & (pts[:, 0] < W)
        & (pts[:, 1] >= 0)
        & (pts[:, 1] < H)
        & np.isfinite(pts).all(axis=1)
    )
    out = np.zeros(len(pts), bool)
    bx = np.clip((pts[ok, 0] // FP_STEP).astype(int), 0, view.shape[1] - 1)
    by = np.clip((pts[ok, 1] // FP_STEP).astype(int), 0, view.shape[0] - 1)
    out[ok] = view[by, bx]
    return out


# ---------------- 5. camera match
def fingerprint(grey: np.ndarray) -> np.ndarray:
    """One block-mean still per second of the window, from its first frame: float32 [k, 45, 80]."""
    return blocks(grey[::FPS])


def _corr(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    x, y = a[m].astype(np.float64), b[m].astype(np.float64)
    if len(x) < 50:
        return 0.0
    x, y = x - x.mean(), y - y.mean()
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(np.dot(x, y) / den) if den > 1e-9 else 0.0


def match_camera(
    fp: np.ndarray, view: np.ndarray, refs: dict[str, np.ndarray]
) -> tuple[str | None, float, dict]:
    """The marked clip whose reference stills best match these, second by second, over the part in
    view.
    """
    scores = {}
    for key, ref in sorted(refs.items()):
        k = min(len(fp), len(ref))
        if k == 0:
            continue
        scores[key] = float(np.mean([_corr(fp[i], ref[i], view) for i in range(k)]))
    if not scores:
        return None, 0.0, {}
    best = max(sorted(scores), key=lambda s: scores[s])
    top = {k: round(v, 4) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:3]}
    return (best if scores[best] >= FP_MATCH else None), scores[best], top


def load_refs(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    z = np.load(path)
    return {k: z[k].astype(np.float32) for k in z.files}


# ---------------- 6. the rear cone in view
def cone_points(rear: np.ndarray, axis: np.ndarray, depth: float, half_deg: float) -> np.ndarray:
    """Floor points filling the rear cone sector: apex at the truck's rear, opening along its
    travel.
    """
    ax = axis / (np.linalg.norm(axis) or 1.0)
    base = math.atan2(float(ax[1]), float(ax[0]))
    pts = []
    for i in range(1, CONE_RADII + 1):
        r = depth * i / CONE_RADII
        for j in range(CONE_ANGLES):
            a = base + math.radians(half_deg) * (2 * j / (CONE_ANGLES - 1) - 1)
            pts.append(rear + r * np.array([math.cos(a), math.sin(a)]))
    return np.asarray(pts)


def cone_view(
    Hm: np.ndarray,
    rear: np.ndarray,
    axis: np.ndarray,
    depth: float,
    half_deg: float,
    view: np.ndarray,
) -> tuple[int, int]:
    """(points inside the frame, points inside the frame and in view) of the cone's floor points on
    one frame.

    The frame's own edge is the site's choice of camera and is not this gate's business; what the
    gate counts is the part of the cone the frame would show but the window does not (cropped or
    blacked out)."""
    pts = cone_points(rear, axis, depth, half_deg)
    Hi = np.linalg.inv(Hm)
    v = np.c_[pts, np.ones(len(pts))] @ Hi.T
    w0 = float((np.r_[rear, 1.0] @ Hi.T)[2])
    img = v[:, :2] / v[:, 2:3]
    ahead = np.sign(v[:, 2]) == np.sign(
        w0
    )  # a floor point past the horizon maps nowhere in the frame
    framed = in_view(np.ones_like(view), img) & ahead
    return int(framed.sum()), int((framed & in_view(view, img)).sum())


def cone_kept(pairs: list[tuple[int, int]]) -> float | None:
    """Pooled share of the framed cone points that are in view; None when the cone never falls
    inside the frame.
    """
    framed = sum(a for a, _ in pairs)
    return round(sum(b for _, b in pairs) / framed, 4) if framed else None


def refusal(field: str, rule_ids: list[str], text: str) -> list[dict]:
    text = " ".join(text.split())[:600]
    missing = "camera.static" if field == "camera.unmatched" else field
    return [
        {
            "rule": r,
            "verdict": "unable_to_rule",
            "missing_fact": missing,
            "frames": [],
            "evidence": text,
        }
        for r in rule_ids
    ]


def text(field: str, **kw) -> str:
    return FIELD_TEXT[field].format(**kw)


def dumps(o) -> str:
    return json.dumps(o, sort_keys=True)
