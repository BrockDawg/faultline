"""The fact sheet: scripts measure every field of the closed vocabulary from the recorded masks and
the frames.

Nothing here calls a model. A value carries an interval from a fixed-seed ensemble that perturbs the
four floor points, the plane scale and every footpoint, so a band is "proven" only when nearly every
draw agrees. The seed, the sigmas and the thresholds were fixed before the first run and are part of
the record.
"""

from __future__ import annotations

import math

import numpy as np

from faultline.adapters.video import floor, sam
from faultline.adapters.video import operator as operator_rule
from faultline.adapters.video.video import FPS, H, W

SEED = 20261028
DRAWS = 200
SIGMA_FLOOR_PX = 10.0  # hand-mark error on a floor point
SCALE_SD = 0.05  # the truck-length scale term
SIGMA_TRUCK_FOOT_PX = 2.0  # SAM footpoint jitter (0.5 to 2 px on identical bytes)
SIGMA_PERSON_FOOT_PX = 3.0
AGREE = 0.975  # a band is proven when this share of draws agrees
HALF = FPS // 2  # 6 frames = half of the 1 s speed window
SG_WIN = 13  # about 1 s at 12 fps
STILL_M = 0.5  # a person whose floor track spans under this is still
STILL_SPOTTER_DEFAULT = (
    True  # the still-spotter exemption (approved per site, 28 Oct); a site.json may set it false
)
# The speed at a track's first and last half second. The centred 1 s window
# has no frames past the track's ends, so every track opened and closed on a second of "unknown"
# moving state, even on a
# truck parked the whole window. EDGE_SPEED reads those frames on the nearest whole second inside
# the same run
# (one-sided); those reads can only complete a "stopped" state (two whole seconds under the moving
# line), never make a
# frame "moving". Gaps inside a track are not bridged. Both switches ride in record.rule_constants()
# and are set here only.
EDGE_SPEED = (
    True  # a constant, never an environment variable: a stray variable cannot move a verdict
)
# Per-frame still-spotter exemption: a person close to the truck on frames whose moving state is
# unread is not
# "unable" when the ruling is the same both ways: stopped is exempt, and moving would continue a
# proven reverse (an
# unread stretch that touches it, velocity against the forks) with this still, vested person (the
# script's colour read,
# never a model read) in the rear cone, which the still-spotter exemption covers.
UNKNOWN_BOTH_WAYS = True  # a constant, never an environment variable
# A truck whose mask is cut by the frame's bottom edge has its lowest mask row on that edge, so its
# footpoint is the frame edge, not where the truck meets the floor: it cannot move down the image
# however the truck
# moves, and on clips 08, 10 and 26 it read "stopped" on every frame while the truck drove in
# (dev/unable/). On such a
# frame a "stopped" read now also needs the mask's top point (the farthest point from the cut edge,
# itself not on the
# top edge) to stay under the moving line over the same window. The top point sits above the floor,
# so its projected
# motion is larger than the truck's floor motion: the check can only be stricter than the truth. It
# never makes a frame
# "moving" (a stopped read it refuses becomes "unknown"), and it applies to the moving state the
# separation and spotter
# rules read; the structure strip's centred state and the speed rule keep their own reads.
CUT_STOP_CHECK = True  # a constant, never an environment variable
CUT_EDGE_PX = 2  # a footpoint within this many pixels of the bottom edge is the frame edge
# The site owner's rulings of 30 Oct 2026, each a constant:
# ruling 4: a reverse seen only through an edge-cut mask is never ruled. A reversing frame's travel
# is read from the
# footpoint over f - HALF .. f + HALF; when the frame's bottom edge cuts the truck's mask on any of
# those frames the
# footpoint is the frame edge, not the floor contact, so that frame proves no reverse. A reverse
# proven only with such
# frames makes the spotter rule "unable to rule" naming truck.reversing (rules.py); the frames are
# kept in the fact sheet.
CUT_REVERSE_CHECK = True
# ruling 3 (with ruling 4's reason): the dock-guide exemption needs the truck's speed into the dock
# zone read under the
# dock line; on a frame whose footpoint is the frame edge that speed is the pinned edge's, so the
# exemption excuses no
# close frame there (the frame stays unread). The guide's place in the zone is still counted and
# written in the ruling.
DOCK_CUT_GUARD = True

# hi-vis (smoke E, unchanged)
BAND = (0.20, 0.60)
MIN_HEIGHT_PX, MIN_BAND_MASK_PX = 40, 60
VESTED_AT, UNVESTED_BELOW = 0.15, 0.05
YG = dict(h=(55.0, 85.0), s=0.45, v=0.50)
OR = dict(h=(8.0, 28.0), s=0.60, v=0.55)
MIN_VEST_FRAMES = 12

# operator rule (smoke K, unchanged): box centre inside the truck's mask box on more than half the
# shared frames
OPERATOR_SHARE = 0.5
# the operator read (seat rule in operator.py): "centre" is the base read above; "seat"
# is seat + centre + ride-along read against every truck seen; "both" keeps the base read and adds
# the
# seat read against any second truck SAM's "forklift" text track finds (a second truck's seated
# driver)
OPERATOR_READ = "both"  # a constant: no environment variable can move a verdict
MIN_TRACK_FRAMES = 6  # half a second of a person, else not a track

# contact and consequence (smoke G, unchanged)
SURROUND_PX, TRUCK_GROW_PX, DIFF_STEP, DIFF_LEVEL, CHANGE_FRAC, CHANGE_FRAMES = (
    40,
    12,
    2,
    30,
    0.03,
    2,
)
STOP_FROM, STOP_TO = 150.0, 0.25
MIN_AREA, COLLAPSE = 250, 0.40
STRIP_HALF_PX = 15
BG_FAR_PX, BG_RATIO = (
    120,
    2.0,
)  # A zone change counts only at twice the change of the background beyond 120 px
# the load-drop read (read in place of two-of-three): three SAM 3.1 video reads,
# one per LOAD_PROMPTS text; a load object falls when its mask centroid drops at least DROP_PX
# within DROP_FRAMES on
# frames where its mask is clear of the truck's mask grown by DROP_TRUCK_GROW_PX (occlusion is not a
# fall), and the drop
# ships only where all three reads see it within DROP_AGREE_FRAMES of each other. These constants
# ride in the ruling's
# rule_constants blob (record.rule_constants), not in the pixel-facts key: no pixel is read by them.
LOAD_PROMPTS = ("cardboard box", "package", "box")
DROP_PX = 40.0
DROP_FRAMES = FPS // 2
DROP_TRUCK_GROW_PX = 12
DROP_AGREE_FRAMES = FPS // 2
DROP_MIN_AREA = 400
# the pairing: a consequence pairs with a strip run only within the consequence window (either side)
# of
# the frame the footprint entered the strip or of the run's last frame, never anywhere else inside a
# long run
PAIRING = "within-window-of-entry-or-end"
AWAY_PX = 20  # Contact: the image step that finds "away from the camera" on the floor

# gates
SHOT_CUT_LEVEL = 40.0  # mean absolute grey change between consecutive frames that is a cut
CAMERA_HELD_PX = (
    2.0  # full-size pixels a half second's background may drift from the first second's
)
HELD_MIN_S = 2.0  # a camera that holds this long from the start is judged on the held span
COMPENSATE_MAX_PX = (
    40.0  # a drift up to this (full-size pixels) is undone point by point, not refused
)
MATCH_PEAK_MIN = 0.08  # and only when every half second's background match is at least this clean


# ---------------- colour
def _hsv(rgb: np.ndarray):
    x = rgb.astype(np.float32) / 255.0
    mx, mn = x.max(-1), x.min(-1)
    d = mx - mn
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm, gm, bm = nz & (mx == r), nz & (mx == g) & (mx != r), nz & (mx == b) & (mx != r) & (mx != g)
    h[rm] = (60.0 * ((g - b)[rm] / d[rm])) % 360.0
    h[gm] = 60.0 * ((b - r)[gm] / d[gm]) + 120.0
    h[bm] = 60.0 * ((r - g)[bm] / d[bm]) + 240.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return h, s, mx


def vest_pixels(rgb: np.ndarray) -> np.ndarray:
    h, s, v = _hsv(rgb)
    yg = (h >= YG["h"][0]) & (h <= YG["h"][1]) & (s >= YG["s"]) & (v >= YG["v"])
    og = (h >= OR["h"][0]) & (h <= OR["h"][1]) & (s >= OR["s"]) & (v >= OR["v"])
    return yg | og


def read_vest(frame: np.ndarray, mask: np.ndarray, box) -> str:
    x0, y0, x1, y1 = box
    height = y1 - y0
    if height < MIN_HEIGHT_PX or x0 <= 1 or y0 <= 1 or x1 >= W - 2 or y1 >= H - 2:
        return "unknown"
    by0, by1 = int(y0 + BAND[0] * height), int(y0 + BAND[1] * height)
    m = mask[by0:by1, x0:x1]
    n = int(m.sum())
    if n < MIN_BAND_MASK_PX:
        return "unknown"
    share = float((vest_pixels(frame[by0:by1, x0:x1]) & m).sum() / n)
    return "vested" if share >= VESTED_AT else "unvested" if share < UNVESTED_BELOW else "unknown"


# ---------------- gates
def shot_cuts(grey: np.ndarray) -> list[int]:
    out = []
    for i in range(1, len(grey)):
        d = float(np.abs(grey[i].astype(np.int16) - grey[i - 1].astype(np.int16)).mean())
        if d > SHOT_CUT_LEVEL:
            out.append(i)
    return out


def phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """(dx, dy, peak): the translation moving b onto a, sub-pixel by a parabolic fit on the
    correlation peak.

    The runner-up's read, rewritten here. The base's version stepped in whole 4 px cells,
    so a slow drift read 0 or 12 px with nothing between.
    """
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    A, B = np.fft.fft2((a - a.mean()) * win), np.fft.fft2((b - b.mean()) * win)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-12
    r = np.fft.ifft2(R).real
    py, px = np.unravel_index(int(np.argmax(r)), r.shape)

    def sub(c, n, get):
        lo, mid, hi = get((c - 1) % n), get(c), get((c + 1) % n)
        d = lo - 2 * mid + hi
        return c + (0.5 * (lo - hi) / d if d else 0.0)

    sy = sub(py, r.shape[0], lambda i: r[i, px])
    sx = sub(px, r.shape[1], lambda j: r[py, j])
    if sy > r.shape[0] / 2:
        sy -= r.shape[0]
    if sx > r.shape[1] / 2:
        sx -= r.shape[1]
    return float(sx), float(sy), float(r.max())


def camera_static(grey: np.ndarray) -> dict:
    """Is the camera held, and if it drifted, by how much on each frame.

    Each half second's median background (a quarter-size grey frame) is phase-matched against the
    first second's.
    static is True when every half second stays within CAMERA_HELD_PX full-size pixels. A camera
    that drifts by a small, cleanly matched translation (under COMPENSATE_MAX_PX, every match peak
    over MATCH_PEAK_MIN) is "compensated": every measured image point is moved back by its frame's
    drift onto the view the floor was marked on, and the consequence read keeps to the frames before
    the drift. A camera that moves more is "held" when at least HELD_MIN_S held from the start (the
    rest is dropped), and False when less did.
    """
    n = len(grey)
    if n < 2 * FPS:
        return {"static": None, "held_frames": 0, "shift_px": None, "offsets": None}
    g = grey[:, ::4, ::4]
    ref = np.median(g[:FPS], axis=0)
    held, worst, low_peak = n, 0.0, 1.0
    offsets = np.zeros((n, 2))
    for s0 in range(0, n, HALF):
        blk = g[s0 : s0 + HALF]
        if len(blk) < 2:
            offsets[s0:] = offsets[s0 - 1] if s0 else 0.0
            break
        dx, dy, peak = phase_shift(ref, np.median(blk, axis=0))
        shift = float(np.hypot(dx, dy)) * 4.0
        offsets[s0 : s0 + HALF] = (
            -dx * 4.0,
            -dy * 4.0,
        )  # image drift of this block against the reference
        if shift > CAMERA_HELD_PX and held == n:
            held = s0
        worst, low_peak = max(worst, shift), min(low_peak, peak)
    if held == n:
        return {"static": True, "held_frames": n, "shift_px": round(worst, 2), "offsets": None}
    if worst <= COMPENSATE_MAX_PX and low_peak >= MATCH_PEAK_MIN:
        return {
            "static": "compensated",
            "held_frames": int(held),
            "shift_px": round(worst, 2),
            "offsets": offsets,
        }
    static = "held" if held >= HELD_MIN_S * FPS else False
    return {
        "static": static,
        "held_frames": int(held),
        "shift_px": round(worst, 2),
        "offsets": None,
    }


# ---------------- context: everything per clip that no draw changes
def strip_polys(structures) -> list[list[tuple[float, float]]]:
    polys = []
    for s in structures:
        (x1, y1), (x2, y2) = s["a"], s["b"]
        n = np.array([y1 - y2, x2 - x1], float)
        n = STRIP_HALF_PX * n / (np.linalg.norm(n) or 1)
        polys.append(
            [
                (x1 + n[0], y1 + n[1]),
                (x2 + n[0], y2 + n[1]),
                (x2 - n[0], y2 - n[1]),
                (x1 - n[0], y1 - n[1]),
            ]
        )
    return polys


def raster(polys) -> np.ndarray:
    """Even-odd polygon fill at pixel centres, numpy only."""
    zone = np.zeros((H, W), dtype=bool)
    yy = np.arange(H) + 0.5
    for poly in polys:
        pts = [(float(x), float(y)) for x, y in poly]
        n = len(pts)
        for row, yc in enumerate(yy):
            xs = []
            for i in range(n):
                (xa, ya), (xb, yb) = pts[i], pts[(i + 1) % n]
                if (ya > yc) != (yb > yc):
                    xs.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                lo, hi = int(math.ceil(xs[j] - 0.5)), int(math.floor(xs[j + 1] - 0.5))
                if hi >= lo:
                    zone[row, max(lo, 0) : min(hi, W - 1) + 1] = True
    return zone


def consequences(grey: np.ndarray, masks: dict[int, np.ndarray], zone: np.ndarray) -> list[list]:
    """Smoke G's consequence onsets: [frame, why] for zone-surround change and abrupt truck stop."""
    if not zone.any() or not masks:
        return []
    region = sam.dilate(zone, SURROUND_PX)
    far = ~sam.dilate(
        zone, BG_FAR_PX
    )  # The background, to tell a local change from a frame-wide one
    rows = []
    grown: dict[int, np.ndarray] = {}
    for i in range(len(grey)):
        m = masks.get(i)
        row = {"area": int(m.sum()) if m is not None else 0, "cx": None, "cy": None, "change": None}
        if m is not None and m.any():
            ys, xs = np.nonzero(m)
            row["cx"], row["cy"] = float(xs.mean()), float(ys.mean())
            grown[i] = sam.dilate(m, TRUCK_GROW_PX)
        else:
            grown[i] = np.zeros_like(zone)
        if i >= DIFF_STEP and (i - DIFF_STEP) in grown:
            live = region & ~(grown[i] | grown[i - DIFF_STEP])
            if live.sum() > 500:
                d = (
                    np.abs(grey[i].astype(np.int16) - grey[i - DIFF_STEP].astype(np.int16))
                    > DIFF_LEVEL
                )
                row["change"] = float((d & live).sum() / live.sum())
                bg = far & ~(grown[i] | grown[i - DIFF_STEP])
                row["bg"] = float((d & bg).sum() / bg.sum()) if bg.sum() > 500 else 0.0
        grown.pop(i - DIFF_STEP - 1, None)
        rows.append(row)
    ok = []
    for i, r in enumerate(rows):
        good = r["area"] >= MIN_AREA
        if good and i > 0 and rows[i - 1]["area"]:
            good = abs(r["area"] - rows[i - 1]["area"]) / rows[i - 1]["area"] <= COLLAPSE
        ok.append(good)
    out = []
    run: list[int] = []
    for i, r in enumerate(rows):
        if (
            r["change"] is not None
            and r["change"] >= CHANGE_FRAC
            and r["change"] >= BG_RATIO * r.get("bg", 0.0)
        ):
            run.append(i)
            if len(run) == CHANGE_FRAMES:
                out.append([run[0], "zone-surround change"])
        else:
            run = []
    spd: list[float | None] = [None] * len(rows)
    for i in range(1, len(rows)):
        if ok[i] and ok[i - 1]:
            spd[i] = (
                math.hypot(rows[i]["cx"] - rows[i - 1]["cx"], rows[i]["cy"] - rows[i - 1]["cy"])
                * FPS
            )
    for i in range(6, len(rows) - 1):
        prev = sorted(s for s in spd[i - 4 : i] if s is not None)
        now = [s for s in spd[i : i + 2] if s is not None]
        if len(prev) >= 3 and len(now) == 2:
            med = prev[len(prev) // 2]
            if med > STOP_FROM and sum(now) / 2 < STOP_TO * med:
                out.append([i, "truck stop"])
    return [list(x) for x in sorted({(f, w) for f, w in out})]


def zone_polys(marks: dict) -> tuple[list, str]:
    structures = marks.get("structures", [])
    polys = list(marks.get("zones", {}).values()) or strip_polys(structures)
    source = "hand zones" if marks.get("zones") else ("base strips" if structures else "none")
    return polys, source


def pixel_facts(
    grey: np.ndarray,
    rgb: np.ndarray,
    tm: dict[int, np.ndarray],
    people: dict[str, dict[int, dict]],
    marks: dict,
) -> dict:
    """Every fact that reads pixels, measured once on the judging host and kept in the record.

    A replay reads this instead of decoding, so a different ffmpeg, scaler or CPU on the replaying
    host cannot move a ruling. `frames_sha256` pins the decoded RGB frames the facts were read from.
    The camera read (with its per-frame drift when compensated), the held span, the shot cuts, every
    person's vest read per frame and the consequence onsets are the only pixel reads build_context
    makes.
    """
    import hashlib

    frames_sha = hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
    shape = [int(x) for x in rgb.shape]
    camera = camera_static(grey)
    if camera["static"] == "held":  # judge only the span the camera held; later frames are dropped
        grey, rgb = grey[: camera["held_frames"]], rgb[: camera["held_frames"]]
    n_frames = len(grey)
    off = camera.get("offsets")
    if off is not None:
        camera["offsets"] = [[float(a), float(b)] for a, b in np.asarray(off)]
    vest: dict[str, dict[str, str]] = {}
    for oid, fr in sorted(people.items()):
        vest[str(oid)] = {
            str(f): read_vest(rgb[f], fr[f]["mask"], fr[f]["box"])
            for f in sorted(fr)
            if f < n_frames
        }
    frames = [f for f in tm if f < n_frames]
    polys, _ = zone_polys(marks)
    # a drifting camera changes every pixel round a structure, so the consequence read keeps to the
    # frames before it
    cg = grey if off is None else grey[: camera["held_frames"]]
    onsets = consequences(cg, tm, raster(polys)) if polys and frames and len(cg) > DIFF_STEP else []
    return {
        "n_frames": int(n_frames),
        "frames_sha256": frames_sha,
        "frames_shape": shape,
        "shot_cuts": [int(x) for x in shot_cuts(grey)],
        "camera": camera,
        "vest": vest,
        "onsets": [[int(f), str(w)] for f, w in onsets],
    }


def build_context(perc, marks: dict, site: dict) -> dict:
    """Per-clip facts that no draw changes: image-space footpoints, envelopes, people, vests, gates,
    consequences.

    Pixels are read only through perc.pixels(marks), the recorded pixel facts; everything else is
    the recorded masks.
    """
    pix = perc.pixels(marks)
    camera = {k: v for k, v in pix["camera"].items() if k != "offsets"}
    n_frames = pix["n_frames"]
    off = pix["camera"].get("offsets")

    def back(f: int, pt):
        """An image point on frame f, moved back onto the marked view (identity unless the drift is
        compensated).
        """
        if off is None or pt is None:
            return pt
        return (
            float(pt[0]) - off[min(f, len(off) - 1)][0],
            float(pt[1]) - off[min(f, len(off) - 1)][1],
        )

    def back_arr(f: int, arr: np.ndarray) -> np.ndarray:
        return arr if off is None or not len(arr) else arr - off[min(f, len(off) - 1)]

    tm = perc.truck_masks()
    frames = sorted(f for f in tm if f < n_frames)
    tboxes = {f: sam.box_of(tm[f]) for f in frames}
    truck_marks = {
        tid: {
            t: ({k: (list(back(FPS * int(t), v)) if v else v) for k, v in e.items()} if e else e)
            for t, e in (tr or {}).items()
        }
        for tid, tr in (marks.get("trucks") or {}).items()
    }
    ctx = {
        "n_frames": n_frames,
        "truck_frames": frames,
        "feet": {f: back(f, sam.foot(tm[f])) for f in frames},
        # The footpoint on the bottom edge (the frame cuts the truck) and the mask's top point
        "foot_cut": {f: foot_on_edge(sam.foot(tm[f])) for f in frames},
        "top": {f: back(f, sam.top_point(tm[f])) for f in frames},
        "env": {f: back_arr(f, sam.envelope(tm[f])) for f in frames},
        "centre": {f: back(f, tuple(sam.envelope(tm[f], 1).mean(axis=0))) for f in frames},
        "tboxes": tboxes,
        "marks": truck_marks,
        "structures": marks.get("structures", []),
        "docks": marks.get("dock_zones", []),
        "floor_points": marks["floor_points"],
        "shot_cuts": list(pix["shot_cuts"]),
        "camera": camera,
        "people": [],
    }
    # fork and rear marks: pick the marked truck nearest the SAM masks (there is one truck per clip
    # in this set)
    best, bd = None, None
    for tid, tr in ctx["marks"].items():
        ds = []
        for t, e in (tr or {}).items():
            b = tboxes.get(FPS * int(t))
            if not e or b is None:
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            ds += [math.hypot(p[0] - cx, p[1] - cy) for p in (e.get("fork"), e.get("rear")) if p]
        if ds and (bd is None or float(np.mean(ds)) < bd):
            best, bd = tid, float(np.mean(ds))
    ctx["fork_marks"] = ctx["marks"].get(best) or {} if best else {}
    # people: SAM objects, the operator rule, the vest read
    extra = perc.extra_trucks() if OPERATOR_READ in ("seat", "both") else []
    ctx["extra_trucks"] = len(extra)
    far_y = min(float(p["img"][1]) for p in marks["floor_points"])
    for oid, fr in sorted(
        perc.person_masks().items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0
    ):
        fs = sorted(f for f in fr if f < n_frames)
        if len(fs) < MIN_TRACK_FRAMES:
            continue
        hits = tot = 0
        for f in fs:
            b = tboxes.get(f)
            if b is None:
                continue
            x0, y0, x1, y1 = fr[f]["box"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            tot += 1
            hits += b[0] <= cx <= b[2] and b[1] <= cy <= b[3]
        operator = tot > 0 and hits / tot > OPERATOR_SHARE
        why = (
            f"box centre inside the truck's box on {hits} of {tot} shared frames"
            if tot
            else "never shared a frame with the truck"
        )
        if OPERATOR_READ == "seat":
            role = operator_rule.classify(
                {f: fr[f]["box"] for f in fs}, [{"boxes": tboxes, "masks": tm}] + extra
            )
            operator, why = role["operator"], role["why"]
        elif OPERATOR_READ == "both" and not operator and extra:
            role = operator_rule.classify({f: fr[f]["box"] for f in fs}, extra)
            if role["operator"]:
                operator, why = True, "second truck: " + role["why"]
        counts = {"vested": 0, "unvested": 0, "unknown": 0}
        reads = pix["vest"].get(str(oid), {})
        feet = {}
        on_edge = {}
        for f in fs:
            m, b = fr[f]["mask"], fr[f]["box"]
            counts[reads.get(str(f), "unknown")] += 1
            ft = sam.foot(m)
            if ft is not None:
                feet[f] = back(f, ft)
            # the feet are what is measured, so only a box cut at the bottom or a side hides them; a
            # head cut by the
            # top edge (a walker coming down the aisle) still shows the feet (the vest read has its
            # own edge test)
            on_edge[f] = b[0] <= 2 or b[2] >= W - 3 or b[3] >= H - 3
            # no metre is read beyond the farthest hand-marked floor point: the plane is
            # extrapolated there
            if ft is not None and feet[f][1] < far_y:
                on_edge[f] = True
        read = counts["vested"] + counts["unvested"] + counts["unknown"]
        ctx["people"].append(
            {
                "id": oid,
                "frames": fs,
                "operator": operator,
                "operator_share": round(hits / tot, 3) if tot else None,
                "operator_why": why,
                "vest_counts": counts,
                "vest_share": {k: (v / read if read else 0.0) for k, v in counts.items()},
                "frames_read": read,
                "feet": feet,
                "on_edge": on_edge,
            }
        )
    # consequence onsets near the structures (measured on pixels, read from the pixel facts)
    polys, ctx["zone_source"] = zone_polys(marks)
    ctx["dock_faces"] = sorted(
        {
            s.get("what", "structure")
            for s in ctx["structures"]
            if any(
                floor.in_poly(((s["a"][0] + s["b"][0]) / 2, (s["a"][1] + s["b"][1]) / 2), z)
                for z in ctx["docks"]
            )
        }
    )
    ctx["onsets"] = [list(x) for x in pix["onsets"]]
    # the load drop: three SAM load reads, asked only where a structure base is marked
    # (the structure rule is the only reader); every reply and its packed-bit masks are kept in the
    # record
    ctx["drops_by_prompt"], ctx["drops"] = {}, []
    if ctx["structures"] and frames:
        reads = [
            load_drops(perc.load_masks_run(r), tm, n_frames, back) for r in range(len(LOAD_PROMPTS))
        ]
        ctx["drops_by_prompt"] = {LOAD_PROMPTS[r]: reads[r] for r in range(len(LOAD_PROMPTS))}
        ctx["drops"] = agreed_drops(reads)
    ctx["onsets"] = sorted(ctx["onsets"] + [[int(k), str(w)] for k, w in ctx["drops"]])
    return ctx


def foot_on_edge(ft) -> bool:
    """A footpoint on the frame's bottom edge: the frame cuts the truck there, so it is not a floor
    contact.
    """
    return ft is not None and float(ft[1]) >= H - 1 - CUT_EDGE_PX


def stopped_frames(
    fr: list[int],
    sp: dict[int, float],
    move: float,
    stop_win: int,
    cut: dict[int, bool] | None = None,
    sp_top: dict[int, float] | None = None,
) -> set[int]:
    """The frames read "stopped": inside a window of stop_win frames whose every speed read is under
    the moving line.

     (CUT_STOP_CHECK): a frame of that window whose footpoint is cut by the bottom edge counts only
     when
    the mask's top point also reads under the line there (sp_top); with no top read it breaks the
    window."""

    def under(j: int) -> bool:
        if sp.get(j) is None or not sp[j] < move:
            return False
        if cut and cut.get(j):
            return sp_top is not None and sp_top.get(j) is not None and sp_top[j] < move
        return True

    ok = {j for j in range(min(fr) - stop_win, max(fr) + stop_win + 1) if under(j)} if fr else set()
    return {
        f
        for f in fr
        if any(all(j in ok for j in range(s, s + stop_win)) for s in range(f - stop_win + 1, f + 1))
    }


def load_drops(
    load: dict[str, dict[int, np.ndarray]], tm: dict[int, np.ndarray], n_frames: int, back=None
) -> list[list]:
    """[frame, object id, fall px] for every load object whose mask centroid falls DROP_PX within
    DROP_FRAMES, measured only on frames where the object is clear of the truck's grown mask (a
    truck passing in front is not a fall).
     read; `back` moves a centroid onto the marked view when the camera drift is compensated."""
    grown: dict[int, np.ndarray] = {}
    out = []
    for oid in sorted(load, key=lambda k: int(k) if k.isdigit() else 0):
        cy = {}
        for f, m in load[oid].items():
            # a mask is a full frame or (y0, x0, the mask cut to its box) (the same pixels, less
            # memory)
            if isinstance(m, tuple):
                y0, x0, m = m
            else:
                y0 = x0 = 0
            if f >= n_frames or int(m.sum()) < DROP_MIN_AREA:
                continue
            t = tm.get(f)
            if t is not None and t.any():
                if f not in grown:
                    grown[f] = sam.dilate(t, DROP_TRUCK_GROW_PX)
                if (m & grown[f][y0 : y0 + m.shape[0], x0 : x0 + m.shape[1]]).any():
                    continue
            ys, xs = np.nonzero(m)
            ys, xs = ys + y0, xs + x0
            c = (float(xs.mean()), float(ys.mean()))
            cy[f] = (back(f, c) if back else c)[1]
        fs = sorted(cy)
        for i, f in enumerate(fs):
            later = [g for g in fs[i + 1 :] if g - f <= DROP_FRAMES]
            if later:
                fall = max(cy[g] for g in later) - cy[f]
                if fall >= DROP_PX:
                    out.append([int(f), str(oid), round(fall, 1)])
                    break
    return out


def agreed_drops(runs: list[list[list]]) -> list[list]:
    """[frame, why] for each drop seen on every one of the three reads, their frames within
    DROP_AGREE_FRAMES of each other; the earliest agreeing frame is the onset. One read with nothing
    decides nothing."""
    if len(runs) < len(LOAD_PROMPTS) or not all(runs):
        return []
    out = []
    for f0, _oid, _fall in runs[0]:
        match = [min(run, key=lambda r: abs(r[0] - f0)) for run in runs[1:]]
        if all(abs(m[0] - f0) <= DROP_AGREE_FRAMES for m in match):
            k = min([f0] + [m[0] for m in match])
            out.append([int(k), "load drop"])
    return [list(x) for x in sorted({(k, w) for k, w in out})]


def vest_state(p: dict, site: dict) -> str:
    """unvested when at least the site share of read frames are unvested; unknown when too few or
    unclear; else vested.
    """
    s = p["vest_share"]
    if p["frames_read"] >= MIN_VEST_FRAMES and s["unvested"] >= site.get("hivis_rule_share", 0.7):
        return "unvested"
    if p["frames_read"] < MIN_VEST_FRAMES or s["unknown"] >= 0.5:
        return "unknown"
    return "vested" if s["vested"] >= 0.5 else "unclear"


# ---------------- one draw
MAX_REDRAW = 20
W_RATIO_MIN = 0.25


def _w(Hm: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """The homography's projective denominator at each image point (its sign flips across the
    plane's horizon).
    """
    return np.c_[pts, np.ones(len(pts))] @ Hm[2]


def draw(ctx: dict, site: dict, rng: np.random.Generator | None) -> dict:
    ip = np.asarray([p["img"] for p in ctx["floor_points"]], float)
    fp = [tuple(p["floor"]) for p in ctx["floor_points"]]
    fr = ctx["truck_frames"]
    Hm = floor.solve([tuple(p) for p in ip], fp)
    # the truck's lowest visible edge (the counterweight's underside, the tines) is not on the
    # floor, so
    # its pixels projected through the floor plane land beyond the truck, scaled away from the
    # camera's floor point by
    # H / (H - h): on the Blender twin +4.0% on every speed and the fork tips ~0.4 m long. Where the
    # site gives the truck's
    # underside height (truck_m.underside_m), every truck pixel is moved to the floor under it, with
    # the camera read off
    # the marked plane itself (floor.camera, the unperturbed plane, once per draw). No height given:
    # no change, so no
    # site here is lifted (dormant). The mask's top point is not lifted: its height
    # is not the underside's.
    lift_h = float((site.get("truck_m") or {}).get("underside_m") or 0.0)
    cam0 = floor.camera(Hm, W, H) if lift_h else None

    def tproj(Hx: np.ndarray, pts) -> np.ndarray:
        return floor.lift(floor.project(Hx, pts), cam0, lift_h)

    if rng is not None:
        # a perturbed plane whose horizon falls across the measured pixels sends a footpoint to
        # infinity (an earlier build's
        # 1,214 m/s on one clip); such a draw is redrawn from the same seeded stream, up to
        # MAX_REDRAW times
        probe = np.asarray(
            [p["img"] for p in ctx["floor_points"]] + [ctx["feet"][f] for f in fr], float
        )
        ref_w = _w(Hm, probe)
        for _ in range(MAX_REDRAW):
            jp = ip + rng.normal(0, SIGMA_FLOOR_PX, ip.shape)
            scale = float(rng.normal(1.0, SCALE_SD))
            Hd = floor.solve([tuple(p) for p in jp], [(x * scale, y * scale) for x, y in fp])
            w = _w(Hd, probe)
            if np.all(np.sign(w) == np.sign(ref_w)) and float(
                np.min(np.abs(w / ref_w))
            ) >= W_RATIO_MIN * float(np.median(np.abs(w / ref_w))):
                break
        Hm = Hd
    out: dict = {"truck": bool(fr)}
    if not fr:
        out.update(
            peak_speed=None,
            moving_frames=0,
            state={},
            reversing_frames=0,
            forward_frames=0,
            direction_unknown_moving=0,
            rev_cut_frames=[],
            rev_clean_frames=0,
            people=[],
            structure=None,
        )
        return out
    MOVE, STOP_WIN = site["moving_mps"], int(site["stopped_window_s"] * FPS) + 1
    tj = np.zeros((len(fr), 2)) if rng is None else rng.normal(0, SIGMA_TRUCK_FOOT_PX, (len(fr), 2))
    idx = {f: i for i, f in enumerate(fr)}
    feet = tproj(Hm, np.asarray([ctx["feet"][f] for f in fr]) + tj)
    pos: dict[int, np.ndarray] = {}
    for run in floor.runs_of(fr):
        if len(run) < 3:
            continue
        sm = floor.smooth(feet[[idx[f] for f in run]], SG_WIN)
        for i, f in enumerate(run):
            pos[f] = sm[i]
    sp = {
        f: float(np.linalg.norm(pos[f + HALF] - pos[f - HALF]))
        for f in fr
        if f - HALF in pos and f + HALF in pos
    }
    sp_c = dict(sp)  # the centred reads only (the speed rule and the structure strip keep these)
    edge_span: dict[int, tuple[int, int]] = {}
    if EDGE_SPEED:
        for run in floor.runs_of(sorted(pos)):
            if len(run) < 2 * HALF + 1:
                continue
            s0, s1 = run[0], run[-1]
            for f in run:
                if f in sp:
                    continue
                a = min(max(f - HALF, s0), s1 - 2 * HALF)
                edge_span[f] = (a, a + 2 * HALF)
                sp[f] = float(np.linalg.norm(pos[a + 2 * HALF] - pos[a]))
    cut = ctx.get("foot_cut") or {}
    sp_top: dict[int, float] | None = None
    if CUT_STOP_CHECK and any(cut.get(f) for f in fr):
        tops = [f for f in fr if (ctx.get("top") or {}).get(f) is not None]
        tpos: dict[int, np.ndarray] = {}
        if tops:
            tidx = {f: i for i, f in enumerate(tops)}
            tp = floor.project(
                Hm,
                np.asarray([ctx["top"][f] for f in tops]) + np.asarray([tj[idx[f]] for f in tops]),
            )
            for run in floor.runs_of(tops):
                if len(run) < 3:
                    continue
                sm = floor.smooth(tp[[tidx[f] for f in run]], SG_WIN)
                for i, f in enumerate(run):
                    tpos[f] = sm[i]
        sp_top = {
            f: float(np.linalg.norm(tpos[f + HALF] - tpos[f - HALF]))
            for f in fr
            if f - HALF in tpos and f + HALF in tpos
        }
        # the top point's track ends read one-sided, exactly as the footpoint's do (a stopped read
        # only)
        if EDGE_SPEED:
            for run in floor.runs_of(sorted(tpos)):
                if len(run) < 2 * HALF + 1:
                    continue
                for f in run:
                    if f not in sp_top:
                        a = min(max(f - HALF, run[0]), run[-1] - 2 * HALF)
                        sp_top[f] = float(np.linalg.norm(tpos[a + 2 * HALF] - tpos[a]))
    stopped_set = stopped_frames(fr, sp, MOVE, STOP_WIN, cut if CUT_STOP_CHECK else None, sp_top)
    state = {}
    for f in fr:
        # moving needs the full centred second (an edge read never makes a frame moving: a one-sided
        # read at a track's
        # end is too weak to put a truck in motion, and a false breach costs more than a miss);
        # stopped may use the edge
        # reads, since two whole seconds under the line are needed either way
        win = [None if j in edge_span else sp.get(j) for j in range(f - HALF, f + HALF + 1)]
        moving = all(v is not None and v > MOVE for v in win)
        state[f] = "moving" if moving else ("stopped" if f in stopped_set else "unknown")
    # the structure strip keeps the centred read: an edge read never turns a strip frame "stopped"
    # (which would drop it
    # from the run and turn an unproven touch into a clear on a one-sided second)
    state_c = {}
    for f in fr:
        stopped_c = any(
            all(sp_c.get(j) is not None and sp_c[j] < MOVE for j in range(s, s + STOP_WIN))
            for s in range(f - STOP_WIN + 1, f + 1)
        )
        state_c[f] = "moving" if state[f] == "moving" else ("stopped" if stopped_c else "unknown")
    out.update(
        peak_speed=max(sp_c.values()) if sp_c else None,
        moving_frames=sum(v == "moving" for v in state.values()),
        stopped_frames=sum(v == "stopped" for v in state.values()),
        state=state,
        speed=sp_c,
        cut_frames=sum(1 for f in fr if cut.get(f)),
        cut_unread=sum(1 for f in fr if cut.get(f) and state[f] == "unknown"),
    )
    env = {f: tproj(Hm, ctx["env"][f] + tj[idx[f]]) for f in fr}
    centre = {f: tproj(Hm, [np.asarray(ctx["centre"][f]) + tj[idx[f]]])[0] for f in fr}
    ufork_sec = {}
    for t, e in (ctx["fork_marks"] or {}).items():
        if not e:
            continue
        k = FPS * int(t)
        F, R = e.get("fork"), e.get("rear")
        if F and R:
            a, b = floor.project(Hm, [F, R])
            u = a - b
        elif F and k in centre:
            u = floor.project(Hm, [F])[0] - centre[k]
        elif R and k in centre:
            u = centre[k] - floor.project(Hm, [R])[0]
        else:
            continue
        n = np.linalg.norm(u)
        if n > 1e-6:
            ufork_sec[k] = u / n

    def ufork(f):
        near = sorted((abs(k - f), k) for k in ufork_sec if abs(k - f) <= FPS)
        return ufork_sec[near[0][1]] if near else None

    direction, front, rear_end, rear_mid, vel = {}, {}, {}, {}, {}
    for f in fr:
        u = ufork(f)
        if f - HALF in pos and f + HALF in pos:
            vel[f] = pos[f + HALF] - pos[f - HALF]
        elif f in edge_span:
            a, b = edge_span[f]
            vel[f] = pos[b] - pos[a]
        if u is not None and len(env[f]):
            d = env[f] @ u
            front[f], rear_end[f] = env[f][int(np.argmax(d))], env[f][int(np.argmin(d))]
            c = env[f].mean(axis=0)
            rear_mid[f] = c + u * float(
                np.min((env[f] - c) @ u)
            )  # the rear end on the truck's centre line
        if state[f] != "moving":
            direction[f] = state[f]
        elif u is None or f not in vel:
            direction[f] = "unknown"
        else:
            direction[f] = "forward" if float(np.dot(vel[f], u)) > 0 else "reversing"
    rev = [f for f in fr if direction[f] == "reversing"]
    rev_runs = [r for r in floor.runs_of(rev) if len(r) >= FPS]
    rev_frames = [f for r in rev_runs for f in r]
    # ruling 4: the reversing frames whose travel is read across a footpoint the bottom edge cuts,
    # and the reverse that
    # stands on uncut reads alone
    rev_cut = [f for f in rev_frames if any(cut.get(j) for j in range(f - HALF, f + HALF + 1))]
    rev_clean_runs = [
        r
        for r in floor.runs_of(
            [f for f in rev if not any(cut.get(j) for j in range(f - HALF, f + HALF + 1))]
        )
        if len(r) >= FPS
    ]
    out.update(rev_cut_frames=rev_cut, rev_clean_frames=sum(len(r) for r in rev_clean_runs))
    out.update(
        reversing_frames=len(rev_frames),
        rev_runs=[[r[0], r[-1]] for r in rev_runs],
        direction_unknown_moving=sum(
            state[f] == "moving" and direction[f] == "unknown" for f in fr
        ),
        forward_frames=sum(direction[f] == "forward" for f in fr),
        fork_known=bool(ufork_sec),
    )
    # people
    SEP, DOCK_MAX = site["pedestrian_separation_m"], site["dock_guide_max_mps"]
    CONE_DEG, CONE_M = (
        site["rear_cone_half_angle_deg"],
        site["rear_cone_depth_truck_lengths"] * site["truck_m"]["length"],
    )
    APEX_SETBACK = 0.5 * site["truck_m"]["width"] / math.tan(math.radians(CONE_DEG))
    docks_img = ctx["docks"]
    docks_floor = [floor.project(Hm, z).mean(axis=0) for z in docks_img]
    rev_set = set(rev_frames)
    # the rear cone in view (gate 6): on the point estimate only, the share of the rear cone the
    # frame covers
    # that is in view; on a reverse the cone opens along the travel, with no proven reverse along
    # the fork axis away
    # from the forks (where a reverse would go)
    out["cone_visible"] = None
    if rng is None and ctx.get("view") is not None:
        from faultline.adapters.video import gates

        if rev_frames:
            pairs = [
                gates.cone_view(Hm, rear_end[k], vel[k], CONE_M, CONE_DEG, ctx["view"])
                for k in rev_frames
                if k in rear_end and k in vel
            ]
        else:
            pairs = [
                gates.cone_view(Hm, rear_end[k], -ufork(k), CONE_M, CONE_DEG, ctx["view"])
                for k in fr
                if k in rear_end and ufork(k) is not None
            ]
        out["cone_visible"] = gates.cone_kept(pairs)

    def in_rear_cone(pt: np.ndarray, k: int) -> bool:
        """The rear cone covers the truck's own rear path: its apex sits inside the truck, set back
        so the cone is already the truck's width at the rear face, and it runs CONE_M behind that
        face."""
        if k not in rear_mid or k not in vel:
            return False
        ax = vel[k] / (np.linalg.norm(vel[k]) or 1)
        w = pt - rear_mid[k]
        if float(np.dot(w, ax)) < 0.0 or float(np.linalg.norm(w)) > CONE_M:
            return False
        wa = pt - (rear_mid[k] - ax * APEX_SETBACK)
        La = float(np.linalg.norm(wa))
        return (
            La < 1e-6
            or math.degrees(math.acos(float(np.clip(np.dot(wa, ax) / La, -1, 1)))) <= CONE_DEG
        )

    still_ok = bool(site.get("still_spotter_exempt", STILL_SPOTTER_DEFAULT))
    rev_adjacent: set[int] = set()
    for a, b in out["rev_runs"]:
        for step, f0 in ((1, b + 1), (-1, a - 1)):
            f = f0
            while state.get(f) == "unknown":
                rev_adjacent.add(f)
                f += step

    def _spotter_if_moving(k: int, pt: np.ndarray, p: dict, span: float) -> bool:
        """On an unread frame touching a proven reverse, with the truck's velocity against its
        forks, this still person, vested by the script's colour read, stands in the rear cone:
        moving or stopped, the ruling is the same."""
        if not still_ok or p.get("vest") != "vested" or span >= STILL_M or k not in vel:
            return False
        u = ufork(k)
        if u is None or float(np.dot(vel[k], u)) >= 0 or not rev_frames:
            return False
        if k not in rev_adjacent:
            return False
        return in_rear_cone(pt, k)

    pouts = []
    for p in ctx["people"]:
        ks = sorted(k for k in p["feet"] if k in env and not p["on_edge"].get(k))
        if not ks:
            pouts.append({"id": p["id"], "frames": 0})
            continue
        fi = np.asarray([p["feet"][k] for k in ks], float)
        if rng is not None:
            fi = fi + rng.normal(0, SIGMA_PERSON_FOOT_PX, fi.shape)
        ff = floor.project(Hm, fi)
        span = float(np.linalg.norm(ff.max(axis=0) - ff.min(axis=0)))
        dmin_move = dmin_all = math.inf
        f_min = None
        exempt_close = cone = close_unknown = close_unknown_cut = close_unknown_dock = (
            dock_frames
        ) = 0
        for i, k in enumerate(ks):
            dist = float(np.min(np.linalg.norm(env[k] - ff[i], axis=1)))
            dmin_all = min(dmin_all, dist)
            dock = False
            in_dock = bool(docks_img) and any(floor.in_poly(p["feet"][k], z) for z in docks_img)
            dock_frames += in_dock
            if (
                docks_img
                and k in vel
                and sp.get(k, 9) < DOCK_MAX
                and not (DOCK_CUT_GUARD and cut.get(k))
            ):
                for z, zc in zip(docks_img, docks_floor, strict=False):
                    if floor.in_poly(p["feet"][k], z) and float(np.dot(vel[k], zc - pos[k])) > 0:
                        dock = True
            in_cone = k in rev_set and in_rear_cone(ff[i], k)
            cone += in_cone
            still_spotter = (
                bool(site.get("still_spotter_exempt", STILL_SPOTTER_DEFAULT))
                and in_cone
                and span < STILL_M
                and p.get("vest") == "vested"
            )
            if state[k] == "moving" and not dock and not still_spotter:
                if dist < dmin_move:
                    dmin_move, f_min = dist, k
            elif dist < SEP:
                if dock or still_spotter or state[k] == "stopped":
                    exempt_close += 1
                elif (
                    UNKNOWN_BOTH_WAYS
                    and state[k] == "unknown"
                    and _spotter_if_moving(k, ff[i], p, span)
                ):
                    exempt_close += 1
                else:
                    close_unknown += 1
                    close_unknown_cut += bool(cut.get(k))
                    close_unknown_dock += in_dock
        if span < STILL_M:
            # a person standing still keeps their place on reverse frames where their feet are cut
            # by the frame edge or
            # unseen: the median of their measured floor positions stands in for those frames
            med = np.median(ff, axis=0)
            ks_set = set(ks)
            cone += sum(1 for k in rev_frames if k not in ks_set and in_rear_cone(med, k))
        pouts.append(
            {
                "id": p["id"],
                "frames": len(ks),
                "min_dist_moving": dmin_move,
                "min_dist_all": dmin_all,
                "frame_min": f_min,
                "close_exempt_frames": exempt_close,
                "close_unknown_frames": close_unknown,
                "close_unknown_cut": close_unknown_cut,
                "close_unknown_dock": close_unknown_dock,
                "dock_frames": dock_frames,
                "span_m": span,
                "cone_share": (cone / len(rev_frames)) if rev_frames else None,
            }
        )
    out["people"] = pouts
    # structures: the truck's floor footprint against each base segment. From a raised camera the
    # mask's lowest pixel in each column is where the truck meets the floor on the side the camera
    # sees (forks
    # included); the side away from the camera is hidden behind the body, so it is carried out to
    # the site's truck
    # length and width along the fork axis (hand fork marks, else the travel direction). Without an
    # axis the measured
    # envelope alone is used, as the base did.
    STRIP, RUN = site["structure_strip_m"], site["structure_run_frames"]
    TL, TW = site["truck_m"]["length"], site["truck_m"]["width"]
    polys: dict[int, np.ndarray] = {}
    for f in fr:
        if not len(env[f]):
            continue
        u = ufork(f)
        if u is None and state[f] == "moving" and f in vel and float(np.linalg.norm(vel[f])) > 1e-6:
            u = vel[f] / float(np.linalg.norm(vel[f]))
        if u is None:
            continue
        c = np.asarray(ctx["centre"][f], float) + tj[idx[f]]
        p0, p1 = tproj(Hm, [c, c - np.array([0.0, AWAY_PX])])
        polys[f] = footprint(env[f], np.asarray(u, float), p1 - p0, TL, TW)
    best = None
    strip_runs = []
    for s in ctx["structures"]:
        a, b = floor.project(Hm, [s["a"], s["b"]])
        run = longest = 0
        first = None
        inside = []
        dmin = dfront = dnear = math.inf
        for f in fr:
            if not len(env[f]):
                run = 0
                continue
            dn = floor.seg_dist_many(env[f], a, b)
            d = min(dn, poly_seg_dist(polys[f], a, b)) if f in polys else dn
            if f in front:
                dfront = min(dfront, floor.seg_dist(front[f], a, b))
            dmin, dnear = min(dmin, d), min(dnear, dn)
            run = run + 1 if d <= STRIP and state_c[f] != "stopped" else 0
            if run:
                inside.append(f)
            longest = max(longest, run)
            if run == RUN and first is None:
                first = f - RUN + 1
        strip_runs += [
            [s.get("what", "structure"), r[0], r[-1]]
            for r in floor.runs_of(inside)
            if len(r) >= RUN
        ]
        row = {
            "name": s.get("what", "structure"),
            "min_front_dist": dmin,
            "min_near_edge_dist": dnear,
            "min_fork_end_dist": dfront,
            "longest_run": longest,
            "first_run_frame": first,
            "footprint_frames": len(polys),
        }
        if best is None or (longest, -dmin) > (best["longest_run"], -best["min_front_dist"]):
            best = row
    out["structure"] = best
    out["strip_runs"] = strip_runs
    out["front_frames"] = len(front)
    return out


def footprint(
    env_floor: np.ndarray, u: np.ndarray, away: np.ndarray, length: float, width: float
) -> np.ndarray:
    """The truck's floor rectangle: the measured near edge along and across the fork axis u, and the
    hidden far edges carried to the site's truck size (or the measured span, when larger). Corners
    in floor metres, in order."""
    u = u / (float(np.linalg.norm(u)) or 1.0)
    v = np.array([-u[1], u[0]])
    pu, pv = env_floor @ u, env_floor @ v
    if float(away @ v) >= 0:
        v0 = float(pv.min())
        v1 = max(float(pv.max()), v0 + width)
    else:
        v1 = float(pv.max())
        v0 = min(float(pv.min()), v1 - width)
    if float(away @ u) >= 0:
        u0 = float(pu.min())
        u1 = max(float(pu.max()), u0 + length)
    else:
        u1 = float(pu.max())
        u0 = min(float(pu.min()), u1 - length)
    return np.array([u0 * u + v0 * v, u1 * u + v0 * v, u1 * u + v1 * v, u0 * u + v1 * v])


def _cross(o, a, b) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def poly_seg_dist(poly: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """Floor distance from a footprint polygon to a base segment; 0 when they touch or cross."""
    if floor.in_poly(tuple(a), poly) or floor.in_poly(tuple(b), poly):
        return 0.0
    n = len(poly)
    best = math.inf
    for i in range(n):
        p1, p2 = poly[i], poly[(i + 1) % n]
        if _cross(p1, p2, a) * _cross(p1, p2, b) < 0 and _cross(a, b, p1) * _cross(a, b, p2) < 0:
            return 0.0
        best = min(
            best,
            floor.seg_dist(p1, a, b),
            floor.seg_dist(p2, a, b),
            floor.seg_dist(a, p1, p2),
            floor.seg_dist(b, p1, p2),
        )
    return best


def contact_pairs(d: dict, onsets: list[list], site: dict, dock_faces=()) -> list[dict]:
    """Every strip run (at least the site's run frames, the truck not stopped) that a consequence
    follows, from one draw.

    An onset pairs only within the consequence window of the frame the footprint entered the strip
    (the run's first frame) or of the run's last frame, either side (the footprint's entry and a
    pixel change at the strip are two reads of one arrival, and the ensemble moves the entry frame
    by a frame or two), never anywhere else inside a long run, so an unrelated change in the middle
    of a long pass along a structure is not a touch. Against a dock face (a structure whose base
    lies in a marked dock zone) a truck stop is the docking itself, so only a change or a drop
    counts there."""
    if not d.get("truck"):
        return []
    CW = int(round(site["consequence_window_s"] * FPS))
    out = []
    for name, a, b in d.get("strip_runs", []):
        for k, why in onsets:
            if why == "truck stop" and name in dock_faces:
                continue
            k = int(k)
            if abs(k - a) <= CW or abs(k - b) <= CW:
                out.append(
                    {
                        "structure": name,
                        "run": [int(a), int(b)],
                        "event": k,
                        "why": str(why),
                        "at": "entry" if abs(k - a) <= CW else "end",
                    }
                )
    return sorted(out, key=lambda x: (x["event"], x["run"][0], x["structure"]))


def ensemble(ctx: dict, site: dict) -> tuple[dict, list[dict]]:
    """The point estimate and DRAWS perturbed draws, from a fixed seed; the same bytes in on every
    run.
    """
    for p in ctx["people"]:
        p["vest"] = vest_state(p, site)
    point = draw(ctx, site, None)
    rng = np.random.default_rng([SEED, len(ctx["truck_frames"]), ctx["n_frames"]])
    draws = [draw(ctx, site, rng) for _ in range(DRAWS)]
    return point, draws


def interval(vals, lo=2.5, hi=97.5):
    v = np.asarray([x for x in vals if x is not None and math.isfinite(x)], float)
    if len(v) == 0:
        return None
    return [round(float(np.percentile(v, lo)), 2), round(float(np.percentile(v, hi)), 2)]
