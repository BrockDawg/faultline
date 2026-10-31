"""steward judge <items.jsonl> --out <preds.jsonl> --rules <dir> --deadline <seconds>: the steward
contract.

One valid line per item, always. Racing windows get faultline's report mode (racing.py): the
evidence pack and an honesty-card verdict, no model call. A forklift item (one whose clip has hand
marks and a site) is routed to the rules judge and its rulings are folded into the contract's shape.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from faultline.adapters.video import racing

VERDICTS = ("no_action", "racing_incident", "penalty", "warning", "dsq")


def fallback(item: dict, why: str) -> dict:
    text = " ".join(why.split())
    if len(text) < 40:
        text += " No measurement was made for this window, so the base-rate verdict stands."
    return {
        "id": item["id"],
        "verdict": racing.verdict_for(float(item.get("end_s", 0)) - float(item.get("start_s", 0))),
        "at_fault": "none",
        "reasoning": text[:1200],
        "rule_refs": racing.REFS["penalty"],
        "confidence": 0.2,
    }


def valid(line: dict) -> bool:
    return (
        isinstance(line.get("id"), str)
        and line.get("verdict") in VERDICTS
        and isinstance(line.get("at_fault"), str)
        and isinstance(line.get("reasoning"), str)
        and 40 <= len(line["reasoning"]) <= 1200
        and isinstance(line.get("rule_refs"), list)
    )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="steward")
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("items")
    j.add_argument("--out", required=True)
    j.add_argument("--rules", default=None)
    j.add_argument("--deadline", type=float, default=None)
    j.add_argument(
        "--no-frames", action="store_true", help="skip the thumbnail read (window length only)"
    )
    args = ap.parse_args(argv)
    started = time.monotonic()
    clips_root = Path(os.environ.get("CLIPS_ROOT", "."))
    items = [
        json.loads(s)
        for s in Path(args.items).read_text(encoding="utf-8").splitlines()
        if s.strip()
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # time plan: the frame read is skipped once the remaining budget is under 90 s plus 4 s an item
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for i, item in enumerate(items):
            left = None if args.deadline is None else args.deadline - (time.monotonic() - started)
            read = not args.no_frames and (left is None or left > 90 + 4 * (len(items) - i))
            try:
                line = racing.steward_line(item, clips_root, read_frames=read)
            except Exception as exc:  # noqa: BLE001  (every item still gets a valid line)
                line = fallback(
                    item,
                    f"faultline could not read this window ({type(exc).__name__}); verdict "
                    "is the window-length base rate.",
                )
            if not valid(line):
                line = fallback(
                    item,
                    "faultline's line failed its own shape check; verdict is the "
                    "window-length base rate.",
                )
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            fh.flush()
    print(
        f"wrote {len(items)} predictions to {out} in {time.monotonic() - started:.0f} s, no "
        "model calls"
    )
    return 0
