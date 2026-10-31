"""Racing, report mode: the script builds the evidence pack and refuses to rule what it cannot
measure.

A broadcast steward review is not a fixed camera: cars are not identified, no floor plane holds, and
the sporting code's verdicts turn on intent and consequence a script cannot see. So the steward's
verdict here is an honesty card:
the window's measured facts (length, shot cuts, motion spikes), the fact it lacks (which car did
what, and whether contact happened), and a verdict that is the base rate of windows of this length
in the development set, said so in the reasoning. No model call decides anything; the model's read
is absent until three runs can agree at no cost.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from faultline.adapters.video import video

SCAN_FPS = 2.0  # thumbnails a second for the motion read
SCAN_WIDTH = 160
MAX_SCAN_S = 240.0  # read at most this much of a window
CUT_LEVEL = 35.0  # mean absolute grey change between thumbnails that is a shot cut
SPIKE_Z = 2.5  # a motion spike sits this many MADs over the window's median
VERDICT_BANDS = [
    (60.0, "no_action"),
    (120.0, "racing_incident"),
    (math.inf, "penalty"),
]  # dev base rates by window length
REFS = {
    "no_action": ["pitbot-library-road-gt#stewarding_review", "pitbot-library-road-gt#racecraft"],
    "racing_incident": [
        "pitbot-library-road-gt#racecraft",
        "pitbot-library-road-gt#incident_reporting",
    ],
    "penalty": ["pitbot-library-road-gt#penalties", "pitbot-library-road-gt#racecraft"],
}


def grey_of(rgb: np.ndarray) -> np.ndarray:
    x = rgb.astype(np.uint16)
    return ((x[..., 0] * 299 + x[..., 1] * 587 + x[..., 2] * 114) // 1000).astype(np.uint8)


def motion(path: Path, start_s: float, end_s: float, budget_s: float | None = None) -> dict:
    """Shot cuts and motion spikes over the window (or its first MAX_SCAN_S), from small
    thumbnails.
    """
    dur = max(0.0, end_s - start_s)
    span = min(dur, MAX_SCAN_S)
    n = max(2, int(span * SCAN_FPS))
    t0 = time.monotonic()
    try:
        th = video.thumbs(path, start_s, start_s + span, n, width=SCAN_WIDTH)
    except Exception as exc:  # noqa: BLE001  (ffmpeg absent or the clip unreadable: the pack says so)
        return {"read": False, "why": f"frames not read: {type(exc).__name__}", "span_s": 0.0}
    if len(th) < 2:
        return {"read": False, "why": "fewer than two frames decoded", "span_s": span}
    g = grey_of(th).astype(np.int16)
    diffs = np.abs(g[1:] - g[:-1]).mean(axis=(1, 2))
    cuts = [int(i + 1) for i, d in enumerate(diffs) if d > CUT_LEVEL]
    inner = np.asarray([d for i, d in enumerate(diffs) if (i + 1) not in cuts], float)
    spikes: list[int] = []
    if len(inner) >= 4:
        med = float(np.median(inner))
        mad = float(np.median(np.abs(inner - med))) or 1.0
        spikes = [
            int(i + 1)
            for i, d in enumerate(diffs)
            if (i + 1) not in cuts and (d - med) / mad > SPIKE_Z
        ]
    return {
        "read": True,
        "span_s": round(span, 1),
        "frames": int(len(th)),
        "shot_cuts": cuts,
        "motion_spikes": spikes,
        "mean_change": round(float(diffs.mean()), 2),
        "seconds": round(time.monotonic() - t0, 1),
    }


def scan(path: Path, start_s: float = 0.0, end_s: float | None = None) -> list[dict]:
    """Contact candidates for a broadcast recording: motion spikes inside one shot, as {t_s, frames,
    evidence}.
    """
    if end_s is None:
        end_s = video.probe(path).get("duration") or start_s + MAX_SCAN_S
    out = []
    t = start_s
    while t < end_s:
        m = motion(path, t, min(end_s, t + MAX_SCAN_S))
        if m.get("read"):
            for s in m["motion_spikes"]:
                ts = t + s / SCAN_FPS
                out.append(
                    {
                        "t_s": round(ts, 1),
                        "frames": [int(round(ts * 30))],
                        "evidence": f"Frame-to-frame change at {ts:.1f} s sits over {SPIKE_Z:g} "
                        "MADs "
                        "above the shot's median with no shot cut; "
                        "a contact candidate for a human steward, not a ruling: no car is "
                        "identified and no contact is measured.",
                    }
                )
        t += MAX_SCAN_S
    return out


def verdict_for(dur: float) -> str:
    for edge, v in VERDICT_BANDS:
        if dur < edge:
            return v
    return "penalty"


def steward_line(item: dict, clips_root: Path, read_frames: bool) -> dict:
    start_s, end_s = float(item.get("start_s", 0.0)), float(item.get("end_s", 0.0))
    dur = max(0.0, end_s - start_s)
    path = clips_root / item["clip"]
    pack = {"window_s": round(dur, 1)}
    if read_frames and path.is_file():
        pack.update(motion(path, start_s, end_s))
    else:
        pack.update(
            {
                "read": False,
                "why": "clip not found" if not path.is_file() else "deadline near, frames not read",
            }
        )
    v = verdict_for(dur)
    facts = f"Measured: a {dur:.0f} s review window"
    if pack.get("read"):
        facts += (
            f"; {len(pack['shot_cuts'])} shot cut(s) and {len(pack['motion_spikes'])} "
            f"motion spike(s) in the first {pack['span_s']:.0f} s "
            f"({pack['frames']} thumbnails)"
        )
    else:
        facts += f"; frames not read ({pack.get('why')})"
    reasoning = (
        facts
        + ". Unmeasured: which car did what, and whether contact happened; a broadcast review "
        "has no fixed floor plane, "
        "so faultline's script cannot rule this window and no model call was made. The "
        "verdict given is the base rate for "
        "windows of this length in the development set "
        f"({'under 60 s' if dur < 60 else 'under 120 s' if dur < 120 else '120 s or longer'}"
        "), "
        "stated as a prior, not a ruling; the human steward's decision is the final."
    )
    return {
        "id": item["id"],
        "verdict": v,
        "at_fault": "none",
        "reasoning": reasoning[:1200],
        "rule_refs": REFS[v],
        "confidence": 0.3,
        "evidence_pack": pack,
        "missing_fact": "contact.consequence",
        "model_read": None,
    }
