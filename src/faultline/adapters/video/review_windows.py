"""Deterministic review windows from full-session racing motion candidates.

These helpers deliberately know nothing about rules, drivers, contact, or a verdict.  They turn
nearby frame-change spikes into a compact list for a human steward to inspect.  Telemetry can be
attached after candidate selection, but never participates in candidate generation or ordering.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy

DEFAULT_BEFORE_S = 4.0
DEFAULT_AFTER_S = 4.0
DEFAULT_GROUP_GAP_S = 4.0


def _number(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _spike_key(item: dict) -> tuple[float, float, str]:
    """A total ordering keeps equivalent scans byte-stable."""
    return (
        _number(item.get("t_s")),
        -_number((item.get("motion") or {}).get("z_score")),
        str(item.get("evidence", "")),
    )


def _block_starts(spikes: list[dict]) -> list[float]:
    starts = {
        _number((spike.get("motion") or {}).get("source_block_s", [None])[0], -1.0)
        for spike in spikes
    }
    return sorted(start for start in starts if start >= 0.0)


def group_motion_spikes(
    spikes: Iterable[dict],
    *,
    before_s: float = DEFAULT_BEFORE_S,
    after_s: float = DEFAULT_AFTER_S,
    group_gap_s: float = DEFAULT_GROUP_GAP_S,
    duration_s: float | None = None,
) -> list[dict]:
    """Group sorted-or-unsorted video spikes into padded, video-only review windows.

    Spikes that land within ``group_gap_s`` are one moment.  This comparison is based on source
    timestamps, so it also merges a moment that crosses the 240-second decoder block boundary.
    Returned order is visual rank, with start time as the deterministic tie-breaker.
    """
    if before_s < 0 or after_s < 0 or group_gap_s < 0:
        raise ValueError("review-window padding and grouping gap must be non-negative")

    ordered = sorted((dict(item) for item in spikes), key=_spike_key)
    groups: list[list[dict]] = []
    for spike in ordered:
        if (
            not groups
            or _number(spike.get("t_s")) - _number(groups[-1][-1].get("t_s")) > group_gap_s
        ):
            groups.append([spike])
        else:
            groups[-1].append(spike)

    windows = []
    for group in groups:
        times = [_number(item.get("t_s")) for item in group]
        strengths = [_number((item.get("motion") or {}).get("z_score")) for item in group]
        cut_proximity = [
            {
                "t_s": round(_number(item.get("t_s")), 3),
                "nearest_hard_cut_s": (item.get("motion") or {}).get("nearest_hard_cut_s"),
                "near_hard_cut": bool((item.get("motion") or {}).get("near_hard_cut")),
            }
            for item in group
        ]
        known_cut_distances = [
            _number(item["nearest_hard_cut_s"])
            for item in cut_proximity
            if item["nearest_hard_cut_s"] is not None
        ]
        start = max(0.0, min(times) - before_s)
        end = max(times) + after_s
        if duration_s is not None:
            end = min(max(0.0, duration_s), end)
        max_strength = max(strengths, default=0.0)
        # Extra nearby samples help choose what to review, but never describe severity or contact.
        visual_score = round(max_strength + 0.25 * max(0, len(group) - 1), 3)
        windows.append(
            {
                "kind": "review_window",
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "center_s": round(sum(times) / len(times), 3),
                "duration_s": round(max(0.0, end - start), 3),
                "visual_score": visual_score,
                "motion": {
                    "spike_count": len(group),
                    "spike_times_s": [round(value, 3) for value in times],
                    "max_z_score": round(max_strength, 3),
                    "sum_z_score": round(sum(strengths), 3),
                    "source_scan_block_starts_s": _block_starts(group),
                    "spike_hard_cut_proximity_s": cut_proximity,
                    "any_spike_near_hard_cut": any(item["near_hard_cut"] for item in cut_proximity),
                    "near_hard_cut_spike_count": sum(
                        item["near_hard_cut"] for item in cut_proximity
                    ),
                    "nearest_hard_cut_s": round(min(known_cut_distances), 3)
                    if known_cut_distances
                    else None,
                },
                "meaning": (
                    "Frame-change activity worth human review; it does not identify a car, "
                    "measure contact, or decide a steward ruling."
                ),
            }
        )

    return sorted(windows, key=lambda item: (-item["visual_score"], item["start_s"], item["end_s"]))


def build_windows(
    spikes: Iterable[dict],
    *,
    start_s: float,
    end_s: float,
    before_s: float = 3.0,
    after_s: float = 3.0,
) -> list[dict]:
    """Build padded windows for the requested source-time range.

    This is the CLI-facing short form.  It clips padding to ``start_s``/``end_s`` while retaining
    the visual-only rank produced by :func:`group_motion_spikes`.
    """
    if end_s < start_s:
        raise ValueError("review-window end must not precede its start")
    in_range = [item for item in spikes if start_s <= _number(item.get("t_s")) <= end_s]
    windows = group_motion_spikes(
        in_range,
        before_s=before_s,
        after_s=after_s,
        duration_s=end_s,
    )
    for window in windows:
        window["start_s"] = round(min(end_s, max(start_s, window["start_s"])), 3)
        window["end_s"] = round(min(end_s, max(start_s, window["end_s"])), 3)
        window["duration_s"] = round(max(0.0, window["end_s"] - window["start_s"]), 3)
    return windows


def annotate_telemetry(
    windows: Iterable[dict], telemetry_events: Iterable[dict], *, time_key: str = "t_s"
) -> list[dict]:
    """Attach events that fall inside each already-ranked review window.

    Telemetry is copied beneath ``telemetry_context``.  The input order and every video candidate
    survive unchanged, which prevents telemetry from becoming an unadvertised locator.
    """
    events = [dict(event) for event in telemetry_events]
    annotated = []
    for window in windows:
        item = deepcopy(window)
        start, end = _number(item.get("start_s")), _number(item.get("end_s"))
        matches = [
            event for event in events if start <= _number(event.get(time_key), float("nan")) <= end
        ]
        item["telemetry_context"] = {"time_key": time_key, "events": matches}
        annotated.append(item)
    return annotated
