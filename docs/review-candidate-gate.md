# Racing review-candidate gate

`faultline-video scan` now adds a `reviewability` object to each JSONL `review_window`. It checks
whether the window has the minimum structure and motion evidence to be useful for inspection. It
does **not** decide that an incident happened, measure contact, identify a car, or make a steward
ruling. `faultline-video review-gate` applies the same check to an existing JSONL file.

## Run it

```sh
uv run faultline-video review-gate runs/windows.jsonl \
  --duration-s 14 --out runs/reviewability.json
```

The input is one JSON `review_window` object per line. The optional source duration lets the gate
reject windows that extend beyond the video. The output is one JSON document with typed results,
reason codes, and counts.

| Disposition | Meaning |
|---|---|
| `accept_for_review` | The time range and frame references are valid; a thresholded motion spike is present and no detected hard cut is flagged. This is a reviewability label, not an incident finding or an instruction to create a human-review task. |
| `insufficient` | Evidence is missing, fallback-only, low confidence, or near a detected hard cut. The candidate stays in the output with this status; this gate does not create a separate human-review queue. |
| `reject` | The input is not a review-window record, the time/frame reference is invalid, or the window exceeds the supplied source duration. This rejects malformed evidence, not an incident. |

The gate intentionally does not use telemetry events to upgrade a candidate, and it does not treat
mask overlap or frame change as proof of contact. The public [contact-rule smoke test](../experiments/2026-10-27-smoke-c-contact-rule/LOG.md)
found a false positive on a negative chase window, while the [racing ceiling test](../experiments/2026-10-28-round-4-racing-ceiling/LOG.md)
found that available mask signals often tracked the wrong camera view. Those results do not support
an automatic incident/no-incident threshold.

The low-confidence fallback windows measured on clips 1 and 13 are both reported as
`insufficient/fallback_only`, not discarded or called incidents. The gate does not yet enforce this
status in a later evidence pipeline; measuring that pipeline's accept/reject policy is future work.
Clip 13's window includes the reported moment around 10 seconds, but its anchor at 8 seconds is only
the largest sampled change. This gate cannot distinguish clip 1's no-incident footage from clip
13's event; it is a reviewability check, not the missing incident detector.
