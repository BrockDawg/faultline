"""The steward contract, run on an items file with no model call, every line checked.

    uv run python scripts/contract_smoke.py <items.jsonl> [--out <preds.jsonl>] [--clips-root <dir>]

Runs `steward judge` on the items, then checks each output line against the contract: one line per
item with the item's id, a verdict from the five, `at_fault` a string, reasoning of 40 to 1200
characters, `rule_refs` a list of `<pack>#<rule>` strings, and any confidence between 0 and 1.
No model call can be made: the model host is pointed at a closed local port and the call ledger at a
fresh file, and the run fails if that ledger holds a single line afterwards.
Prints `contract smoke: N of M lines valid, 0 model calls` and exits 0 only when every item has a
valid line.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VERDICTS = {"no_action", "racing_incident", "penalty", "warning", "dsq"}


def valid(line: dict, ids: set[str]) -> list[str]:
    bad = []
    if line.get("id") not in ids:
        bad.append("id")
    if line.get("verdict") not in VERDICTS:
        bad.append("verdict")
    if not isinstance(line.get("at_fault"), str):
        bad.append("at_fault")
    r = line.get("reasoning")
    if not isinstance(r, str) or not 40 <= len(r) <= 1200:
        bad.append("reasoning")
    refs = line.get("rule_refs")
    if not isinstance(refs, list) or not all(isinstance(x, str) and "#" in x for x in refs):
        bad.append("rule_refs")
    c = line.get("confidence")
    if c is not None and not (isinstance(c, (int, float)) and 0 <= c <= 1):
        bad.append("confidence")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="contract_smoke")
    ap.add_argument("items")
    ap.add_argument("--out", default=None)
    ap.add_argument("--clips-root", default=None)
    args = ap.parse_args(argv)
    items = [
        json.loads(s)
        for s in Path(args.items).read_text(encoding="utf-8").splitlines()
        if s.strip()
    ]
    ids = {it["id"] for it in items}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(args.out) if args.out else Path(tmp) / "preds.jsonl"
        ledger = Path(tmp) / "ledger.jsonl"
        env = dict(os.environ)
        env.update(
            {
                "MODEL_API_BASE": "http://127.0.0.1:9/closed",
                "MODEL_API_KEY": "none",
                "STEWARD_ENV_FILE": "",
                "FAULTLINE_LEDGER": str(ledger),
                "FAULTLINE_RECORD": str(Path(tmp) / "record"),
            }
        )
        if args.clips_root:
            env["CLIPS_ROOT"] = args.clips_root
        cmd = [
            sys.executable,
            "-c",
            "import sys; from faultline.adapters.video.steward_cli import main; sys.exit(main())",
            "judge",
            args.items,
            "--out",
            str(out),
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            print(f"contract smoke: steward judge exited {proc.returncode}")
            return 1
        lines = [json.loads(s) for s in out.read_text(encoding="utf-8").splitlines() if s.strip()]
        calls = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.is_file() else 0
    good = 0
    seen: set[str] = set()
    for ln in lines:
        bad = valid(ln, ids)
        if bad:
            print(f"  {ln.get('id')}: invalid {', '.join(bad)}")
        elif ln["id"] not in seen:
            good += 1
            seen.add(ln["id"])
    print(f"contract smoke: {good} of {len(items)} lines valid, {calls} model calls")
    return 0 if good == len(items) == len(lines) and calls == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
