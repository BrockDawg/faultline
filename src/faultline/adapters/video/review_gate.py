"""Conservative, deterministic reviewability gate for video review windows.

This gate decides only whether a candidate is structurally usable for a steward to inspect.
It does not decide whether an incident occurred, whether contact happened, or who is at fault.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA = 1
KIND = "reviewability_gate"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _result(
    window: Mapping[str, Any], disposition: str, reason: str, explanation: str
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "window": dict(window),
        "disposition": disposition,
        "reason": reason,
        "explanation": explanation,
        "meaning": (
            "This is a reviewability check only. It does not detect an incident, measure contact, "
            "identify a car, or decide a steward ruling."
        ),
    }


def assess_window(
    value: Mapping[str, Any], *, video_duration_s: float | None = None
) -> dict[str, Any]:
    """Classify one scan window as reviewable, rejected as invalid, or insufficient.

    ``accept_for_review`` means a human can inspect a valid window containing at least one
    thresholded motion spike away from a detected hard cut. It does not mean an incident was found.
    Low-confidence fallback-only windows remain available as ``insufficient`` for human review;
    the gate never throws them away merely because the signal is weak.
    """
    window = dict(value) if isinstance(value, Mapping) else {}
    if window.get("kind") != "review_window":
        return _result(
            window,
            "reject",
            "not_a_review_window",
            "The input is not a review_window record.",
        )

    start = _finite_number(window.get("start_s"))
    end = _finite_number(window.get("end_s"))
    if start is None or end is None or start < 0 or end <= start:
        return _result(
            window,
            "reject",
            "invalid_time_range",
            "The candidate has no finite, positive source-time range.",
        )

    duration = _finite_number(video_duration_s)
    if video_duration_s is not None and duration is None:
        return _result(
            window,
            "reject",
            "invalid_video_duration",
            "The supplied video duration is not a finite number.",
        )
    if duration is not None and (duration <= 0 or end > duration):
        return _result(
            window,
            "reject",
            "outside_video",
            "The candidate extends beyond the supplied video duration.",
        )

    frames = window.get("frames")
    if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)) or not frames:
        return _result(
            window,
            "insufficient",
            "no_frame_references",
            "The window has no frame references to inspect; it is retained for review.",
        )
    frame_numbers = [_finite_number(frame) for frame in frames]
    if any(frame is None or frame < 0 or not frame.is_integer() for frame in frame_numbers):
        return _result(
            window,
            "reject",
            "invalid_frame_reference",
            "At least one frame reference is not a finite, non-negative number.",
        )

    motion = window.get("motion")
    if not isinstance(motion, Mapping):
        return _result(
            window,
            "insufficient",
            "missing_motion_measurements",
            "No motion measurements accompany the candidate; it is retained for review.",
        )

    strong = _finite_number(motion.get("strong_spike_count"))
    fallback = _finite_number(motion.get("fallback_spike_count"))
    spike_count = _finite_number(motion.get("spike_count"))
    if (
        strong is None
        or fallback is None
        or spike_count is None
        or min(strong, fallback, spike_count) < 0
        or not all(number.is_integer() for number in (strong, fallback, spike_count))
        or strong + fallback != spike_count
    ):
        return _result(
            window,
            "insufficient",
            "incomplete_motion_measurements",
            "The motion counts are missing or inconsistent; the candidate is retained for review.",
        )

    if strong == 0:
        return _result(
            window,
            "insufficient",
            "fallback_only",
            "Only a low-confidence fallback frame-change signal exists; this does not support an "
            "incident finding, so the candidate is retained for a human to inspect.",
        )

    if bool(motion.get("any_spike_near_hard_cut")):
        return _result(
            window,
            "insufficient",
            "motion_near_hard_cut",
            "A detected hard cut may explain the motion signal; the candidate is retained for a "
            "human to inspect.",
        )

    if not isinstance(motion.get("any_spike_near_hard_cut"), bool):
        return _result(
            window,
            "insufficient",
            "unknown_cut_context",
            "The scan does not say whether the motion is near a detected hard cut; the candidate "
            "is retained for review.",
        )

    if window.get("confidence") != "experimental":
        return _result(
            window,
            "insufficient",
            "low_confidence_signal",
            "The source labels this candidate low confidence; it is retained for human review.",
        )

    return _result(
        window,
        "accept_for_review",
        "valid_thresholded_motion",
        "The candidate has a valid time range, frame references, and thresholded motion away from "
        "a detected hard cut. It is suitable to inspect, not evidence that an incident occurred.",
    )


def gate_document(
    windows: Sequence[Mapping[str, Any]], *, video_duration_s: float | None = None
) -> dict[str, Any]:
    """Return a deterministic document for a sequence of candidate windows."""
    results = [assess_window(window, video_duration_s=video_duration_s) for window in windows]
    counts = {
        status: sum(item["disposition"] == status for item in results)
        for status in ("accept_for_review", "insufficient", "reject")
    }
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "meaning": (
            "Reviewability only; accepted candidates are eligible for human inspection, not "
            "incident findings or steward rulings."
        ),
        "video_duration_s": video_duration_s,
        "counts": counts,
        "windows": results,
    }
