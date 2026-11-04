from __future__ import annotations

import json

from faultline.adapters.video import review_gate
from faultline.adapters.video.cli import main


def candidate(**updates):
    row = {
        "kind": "review_window",
        "start_s": 5.0,
        "end_s": 11.0,
        "center_s": 8.0,
        "frames": [240],
        "confidence": "experimental",
        "motion": {
            "spike_count": 1,
            "strong_spike_count": 1,
            "fallback_spike_count": 0,
            "any_spike_near_hard_cut": False,
        },
    }
    row.update(updates)
    return row


def test_thresholded_motion_is_accepted_only_for_human_review():
    result = review_gate.assess_window(candidate())

    assert result["disposition"] == "accept_for_review"
    assert result["reason"] == "valid_thresholded_motion"
    assert "not evidence that an incident occurred" in result["explanation"]
    assert "verdict" not in result


def test_low_confidence_fallback_is_insufficient_and_preserved():
    fallback = candidate(
        confidence="low",
        motion={
            "spike_count": 1,
            "strong_spike_count": 0,
            "fallback_spike_count": 1,
            "any_spike_near_hard_cut": False,
        },
    )

    result = review_gate.assess_window(fallback)

    assert result["disposition"] == "insufficient"
    assert result["reason"] == "fallback_only"
    assert result["window"] == fallback


def test_hard_cut_motion_is_insufficient_not_an_incident_rejection():
    row = candidate(
        motion={
            "spike_count": 1,
            "strong_spike_count": 1,
            "fallback_spike_count": 0,
            "any_spike_near_hard_cut": True,
        }
    )

    result = review_gate.assess_window(row)

    assert result["disposition"] == "insufficient"
    assert result["reason"] == "motion_near_hard_cut"
    assert result["window"] == row


def test_invalid_ranges_and_bad_frame_references_are_rejected():
    invalid_range = review_gate.assess_window(candidate(end_s=5.0))
    beyond_video = review_gate.assess_window(candidate(), video_duration_s=10.0)
    invalid_frame = review_gate.assess_window(candidate(frames=[-1]))

    assert invalid_range["disposition"] == "reject"
    assert invalid_range["reason"] == "invalid_time_range"
    assert beyond_video["disposition"] == "reject"
    assert beyond_video["reason"] == "outside_video"
    assert invalid_frame["disposition"] == "reject"
    assert invalid_frame["reason"] == "invalid_frame_reference"


def test_missing_motion_data_is_insufficient():
    result = review_gate.assess_window(candidate(motion=None))

    assert result["disposition"] == "insufficient"
    assert result["reason"] == "missing_motion_measurements"


def test_missing_cut_context_is_insufficient():
    row = candidate(
        motion={
            "spike_count": 1,
            "strong_spike_count": 1,
            "fallback_spike_count": 0,
        }
    )

    result = review_gate.assess_window(row)

    assert result["disposition"] == "insufficient"
    assert result["reason"] == "unknown_cut_context"


def test_unknown_confidence_is_insufficient():
    result = review_gate.assess_window(candidate(confidence="unrecognized"))

    assert result["disposition"] == "insufficient"
    assert result["reason"] == "low_confidence_signal"


def test_gate_document_counts_typed_outcomes():
    result = review_gate.gate_document(
        [
            candidate(),
            candidate(
                confidence="low",
                motion={
                    "spike_count": 1,
                    "strong_spike_count": 0,
                    "fallback_spike_count": 1,
                    "any_spike_near_hard_cut": False,
                },
            ),
            candidate(end_s=5.0),
        ]
    )

    assert result["counts"] == {"accept_for_review": 1, "insufficient": 1, "reject": 1}


def test_review_gate_cli_reads_scan_jsonl_and_writes_document(tmp_path):
    source = tmp_path / "windows.jsonl"
    output = tmp_path / "reviewability.json"
    source.write_text(json.dumps(candidate()) + "\n", encoding="utf-8")

    assert main(["review-gate", str(source), "--out", str(output), "--duration-s", "14"]) == 0
    document = json.loads(output.read_text(encoding="utf-8"))

    assert document["kind"] == "reviewability_gate"
    assert document["counts"]["accept_for_review"] == 1
    assert document["windows"][0]["disposition"] == "accept_for_review"


def test_scan_embeds_reviewability_for_every_candidate(tmp_path, monkeypatch):
    from faultline.adapters.video import racing, video

    source = tmp_path / "recording.mp4"
    source.write_bytes(b"test video placeholder")
    output = tmp_path / "windows.jsonl"
    monkeypatch.setattr(video, "probe", lambda _path: {"duration": 14.0})
    monkeypatch.setattr(
        racing,
        "scan",
        lambda *_args: [
            {
                "t_s": 4.0,
                "frames": [120],
                "evidence": "largest sampled change; no thresholded spike",
                "motion": {"z_score": 2.1, "fallback": True, "near_hard_cut": False},
            },
            {
                "t_s": 10.0,
                "frames": [300],
                "evidence": "thresholded frame change",
                "motion": {"z_score": 3.0, "fallback": False, "near_hard_cut": False},
            },
        ],
    )

    assert main(["scan", str(source), "--out", str(output)]) == 0
    windows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert len(windows) == 2
    assert {w["reviewability"]["disposition"] for w in windows} == {
        "accept_for_review",
        "insufficient",
    }
    fallback = next(w for w in windows if w["confidence"] == "low")
    assert fallback["reviewability"]["reason"] == "fallback_only"
    assert fallback["reviewability"]["disposition"] == "insufficient"
