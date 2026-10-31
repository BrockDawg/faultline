"""The floor plane: a homography from four hand-marked floor points, by direct linear transform in
numpy.

Smoke I's method (28 Oct 2026), unchanged. Image pixels in, floor metres out. Deterministic.
"""

from __future__ import annotations

import math

import numpy as np


def _norm(pts: np.ndarray) -> np.ndarray:
    c = pts.mean(axis=0)
    s = math.sqrt(2.0) / float(np.mean(np.linalg.norm(pts - c, axis=1)))
    return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])


def solve(img_pts, floor_pts) -> np.ndarray:
    """3x3 H with floor ~ H @ image, from four or more point pairs."""
    a = np.asarray(img_pts, dtype=float)
    b = np.asarray(floor_pts, dtype=float)
    Ta, Tb = _norm(a), _norm(b)
    ah = (Ta @ np.c_[a, np.ones(len(a))].T).T
    bh = (Tb @ np.c_[b, np.ones(len(b))].T).T
    rows = []
    for (x, y, _), (u, v, _) in zip(ah, bh, strict=False):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    Hn = vt[-1].reshape(3, 3)
    Hm = np.linalg.inv(Tb) @ Hn @ Ta
    return Hm / Hm[2, 2]


def project(Hm: np.ndarray, pts) -> np.ndarray:
    pts = np.asarray(pts, dtype=float).reshape(-1, 2)
    v = np.c_[pts, np.ones(len(pts))] @ Hm.T
    return v[:, :2] / v[:, 2:3]


FOCAL_AGREE = (
    1.25  # the plane's two focal estimates must agree this closely, or it holds no pinhole camera
)


def camera(Hm: np.ndarray, width: int, height: int) -> dict | None:
    """The camera's floor point and height, read from the floor plane alone.

    Hm maps image pixels to floor metres. With square pixels, no skew and the principal point at the
    image centre, the plane's image homography K [r1 r2 t] gives two estimates of the focal length
    (r1 . r2 = 0 and |r1| = |r2|); both must be positive and agree within FOCAL_AGREE, else the four
    marks hold no consistent pinhole camera and None is returned (a hand-marked plane on generated
    footage, or a marker's guessed far corners: on the 26 Kling clips' planes and on the twin's m1
    marks none agrees, so nothing is lifted there). Then the pose, and the camera centre -R^T t:
    its floor point and height above the floor. None too when the camera sits on or under the floor.
    On the twin's true plane this returns the scene camera to the millimetre (dev/twin/LOG.md).
    """
    Hf = np.linalg.inv(np.asarray(Hm, float))
    T = np.array([[1.0, 0.0, -width / 2.0], [0.0, 1.0, -height / 2.0], [0.0, 0.0, 1.0]])
    A = T @ Hf
    a, b = A[:, 0], A[:, 1]
    if abs(a[2] * b[2]) < 1e-12 or abs(a[2] ** 2 - b[2] ** 2) < 1e-12:
        return None
    est = [
        -(a[0] * b[0] + a[1] * b[1]) / (a[2] * b[2]),
        -(a[0] ** 2 + a[1] ** 2 - b[0] ** 2 - b[1] ** 2) / (a[2] ** 2 - b[2] ** 2),
    ]
    if not all(e > 0 and math.isfinite(e) for e in est):
        return None
    f1, f2 = math.sqrt(est[0]), math.sqrt(est[1])
    if max(f1, f2) > FOCAL_AGREE * min(f1, f2):
        return None
    f = math.sqrt(float(np.mean(est)))
    M = np.diag([1.0 / f, 1.0 / f, 1.0]) @ A
    lam = 1.0 / math.sqrt(float(np.linalg.norm(M[:, 0]) * np.linalg.norm(M[:, 1])))
    r1, r2, t = M[:, 0] * lam, M[:, 1] * lam, M[:, 2] * lam
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    R = np.c_[r1, r2, np.cross(r1, r2)]
    C = -R.T @ t
    z = abs(float(C[2]))
    if not math.isfinite(z) or z < 1e-3:
        return None
    return {"focal_px": f, "ground": np.array([float(C[0]), float(C[1])]), "height_m": z}


def lift(pts_floor: np.ndarray, cam: dict | None, h: float) -> np.ndarray:
    """Floor points read off image points that sit h metres above the floor, moved to the floor
    point under them.

    A pixel projected through the floor plane lands where its ray meets the floor; a point h above
    the floor on that ray stands over the spot (1 - h / camera height) of the way from the camera's
    floor point. No camera or h = 0: unchanged.
    """
    p = np.asarray(pts_floor, float)
    if cam is None or not h or not len(p):
        return p
    g = cam["ground"]
    return g + (p - g) * (1.0 - float(h) / cam["height_m"])


def seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    t = 0.0 if not ab.any() else float(np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def seg_dist_many(pts: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """The smallest distance from any of pts (n, 2) to the segment a-b."""
    pts = np.asarray(pts, dtype=float).reshape(-1, 2)
    if not len(pts):
        return math.inf
    ab = b - a
    den = float(np.dot(ab, ab))
    t = np.zeros(len(pts)) if den == 0 else np.clip((pts - a) @ ab / den, 0.0, 1.0)
    return float(np.min(np.linalg.norm(pts - (a + t[:, None] * ab), axis=1)))


def in_poly(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def savgol_coeffs(win: int, order: int = 2) -> np.ndarray:
    half = win // 2
    x = np.arange(-half, half + 1, dtype=float)
    A = np.vander(x, order + 1, increasing=True)
    return np.linalg.pinv(A)[0]


def smooth(series, win: int) -> np.ndarray:
    """Centred Savitzky-Golay over an (n, 2) series; the window shrinks (odd) at the ends."""
    s = np.asarray(series, dtype=float)
    n = len(s)
    out = np.empty_like(s)
    for i in range(n):
        half = min(win // 2, i, n - 1 - i)
        if half < 1:
            out[i] = s[i]
            continue
        c = savgol_coeffs(2 * half + 1)
        out[i] = c @ s[i - half : i + half + 1]
    return out


def runs_of(frames):
    runs, cur = [], []
    for f in frames:
        if cur and f != cur[-1] + 1:
            runs.append(cur)
            cur = []
        cur.append(f)
    if cur:
        runs.append(cur)
    return runs
