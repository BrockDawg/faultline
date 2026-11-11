"""The racing panel's live checks, one per process: prints JSON lines for the worker.

    python -m faultline.adapters.pitbot.replay_one --racing <dir> --protest <id>
    python -m faultline.adapters.pitbot.replay_one --racing <dir> --limits

`--protest <id>`: for each arm, the protest's one line is copied into a temp folder laid out
the way replay finds things beside a preds file (`_frames_dir_for`, `_ledger_dir_for`):
`preds-armN.jsonl`, `preds-armN.jsonl.record/<record>.json`, `preds-armN.jsonl.frames/<sha>.jpg`
for every frame its bundle names, and `ledger/<key>.json` for every reply key it names. Then
`faultline.cli.replay` runs on it: the bundle hash, the frame hashes and the model's read rebuilt
from the ledger, all checked. The frame and ledger overrides (`FAULTLINE_FRAMES_DIR`,
`FAULTLINE_LEDGER_DIR`) are cleared first so the copy is what is read.

`--limits` follows `bundle.limits_mode(racing_dir)`:
- "rerule": `pitbot.cli.limits` on `<racing>/league.json` into a temp file, then a byte compare
  with the stored `limits.jsonl`. The league's feed paths are relative to the racing dir and
  `Feed.load` takes them as given, so this process changes its working folder to the racing
  dir before the call (one job per process, so that is safe).
- "checked": `faultline.cli.replay` on the stored limits lines, one session at a time.
One `line` event per session, labelled from `session_map.json` ("Race N · HEAT 1").

Output, one JSON object per line on stdout:
`{"event": "stage", "name": "start|record|rebuild|seal"}` at the points the code passes,
`{"event": "line", ...}` per session (limits only), then one
`{"event": "result", "id", "match", "record_shipped", "record_rebuilt", "seconds", ...}`.
A record that does not rebuild is `match: false` with a plain `why`; an unreadable racing
folder or an unknown id is `{"event": "error", "message": ...}` and exit 2. No line carries a
session number, a path or a name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from faultline import cli, record
from faultline.adapters.pitbot import bundle
from faultline.adapters.pitbot import cli as pitbot

ARMS = (1, 2)
NOT_REBUILT = "the stored record did not rebuild"


def _emit(event: str, **fields: Any) -> None:
    # ASCII only: a pipe's encoding differs by platform, and "·" must survive it as ·.
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


class _Refused(Exception):
    """An input the check cannot start from; the message is plain words."""


def _rows(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """(raw line text, parsed row) for every non-blank line, in file order."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise _Refused(f"{path.name} cannot be read.") from None
    out = []
    for raw in text.split("\n"):
        if raw.strip():
            out.append((raw, json.loads(raw)))
    return out


def _copy_one(src_preds: Path, raw: str, row: dict[str, Any], dest: Path) -> Path:
    """Lay one line out in `dest` with its bundle, its frames and its ledger replies."""
    dest.mkdir(parents=True, exist_ok=True)
    preds = dest / src_preds.name
    preds.write_text(raw + "\n", encoding="utf-8", newline="\n")
    sha = row.get("record")
    if not isinstance(sha, str):
        return preds
    src_bundle = Path(f"{src_preds}.record") / f"{sha}.json"
    if not src_bundle.is_file():
        return preds  # replay refuses the missing bundle: a mismatch, not a crash
    (Path(f"{preds}.record")).mkdir(exist_ok=True)
    shutil.copyfile(src_bundle, Path(f"{preds}.record") / f"{sha}.json")
    try:
        inputs = json.loads(src_bundle.read_text(encoding="utf-8")).get("inputs") or {}
    except (json.JSONDecodeError, AttributeError):
        return preds
    if not isinstance(inputs, dict):
        return preds
    shas: set[str] = set()
    for value in (inputs.get("frame_sha256"), (inputs.get("model_call") or {}).get("frame_sha256")):
        if isinstance(value, list):
            shas.update(s for s in value if isinstance(s, str))
    src_frames = Path(f"{src_preds}{pitbot.FRAMES_SUFFIX}")
    frames = Path(f"{preds}{pitbot.FRAMES_SUFFIX}")
    for s in sorted(shas):
        if (src_frames / f"{s}.jpg").is_file():
            frames.mkdir(exist_ok=True)
            shutil.copyfile(src_frames / f"{s}.jpg", frames / f"{s}.jpg")
    keys = inputs.get("ledger_keys")
    if isinstance(keys, list):
        src_ledger = src_preds.parent / pitbot.LEDGER_NAME
        ledger = dest / pitbot.LEDGER_NAME
        for k in keys:
            if isinstance(k, str) and (src_ledger / f"{k}.json").is_file():
                ledger.mkdir(exist_ok=True)
                shutil.copyfile(src_ledger / f"{k}.json", ledger / f"{k}.json")
    return preds


def _replay(preds: Path, out: Path) -> tuple[bool, bytes | None]:
    """(match, rebuilt bytes): replay `preds` into `out`; a refusal is a mismatch."""
    try:
        cli.replay(preds, out)
    except (ValueError, record.RecordError, OSError):
        return False, None
    rebuilt = out.read_bytes()
    return rebuilt == preds.read_bytes(), rebuilt


def _record_of(rebuilt: bytes | None) -> str | None:
    if not rebuilt:
        return None
    rows = [json.loads(t) for t in rebuilt.decode("utf-8").split("\n") if t.strip()]
    return rows[0].get("record") if len(rows) == 1 else None


def protest(racing: Path, pid: str, tmp: Path) -> int:
    t0 = time.monotonic()
    found: dict[int, tuple[str, dict[str, Any]]] = {}
    for arm in ARMS:
        src = racing / bundle.ARM_FILES[arm]
        hit = [(raw, row) for raw, row in _rows(src) if row.get("id") == pid]
        if len(hit) != 1:
            raise _Refused(f"protest {pid} is not in the record.")
        found[arm] = hit[0]
    _emit("stage", name="record")
    lines = []
    for arm in ARMS:
        raw, row = found[arm]
        src = racing / bundle.ARM_FILES[arm]
        preds = _copy_one(src, raw, row, tmp / f"arm{arm}")
        match, rebuilt = _replay(preds, tmp / f"arm{arm}" / "out" / preds.name)
        lines.append(
            {
                "arm": arm,
                "match": match,
                "record_shipped": row.get("record"),
                "record_rebuilt": _record_of(rebuilt) if match else None,
                "verdict": row.get("verdict"),
            }
        )
    _emit("stage", name="rebuild")
    ok = all(x["match"] for x in lines)
    _emit("stage", name="seal")
    result: dict[str, Any] = {
        "id": pid,
        "label": f"Protest {pid}",
        "match": ok,
        "record_shipped": {f"arm{x['arm']}": x["record_shipped"] for x in lines},
        "record_rebuilt": {f"arm{x['arm']}": x["record_rebuilt"] for x in lines},
        "lines": lines,
        "rulings": [{"rule": found[2][1].get("rule"), "verdict": found[2][1].get("verdict")}],
        "seconds": round(time.monotonic() - t0, 2),
    }
    if not ok:
        result["why"] = NOT_REBUILT
    _emit("result", **result)
    return 0


def _by_session(rows: list[tuple[str, dict[str, Any]]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw, row in rows:
        out.setdefault(str((row.get("window") or {}).get("session")), []).append(raw)
    return out


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def limits(racing: Path, tmp: Path) -> int:
    t0 = time.monotonic()
    mode = bundle.limits_mode(racing)
    try:
        labels = bundle.read_session_map(racing)
    except bundle.BundleError:
        raise _Refused("the session map is missing.") from None
    stored_path = racing / bundle.LIMITS_FILE
    stored_rows = _rows(stored_path)
    stored = stored_path.read_bytes()
    stored_by = _by_session(stored_rows)
    if any(k not in labels for k in stored_by):
        raise _Refused("a stored line names a session the map does not hold.")
    _emit("stage", name="record")
    rebuilt_by: dict[str, list[str]] = {}
    rebuilt: bytes | None = None
    if mode == "rerule":
        out = tmp / bundle.LIMITS_FILE
        here = Path.cwd()
        try:
            os.chdir(racing)  # the league's feed paths resolve from the racing dir
            pitbot.limits(Path("league.json"), out)
            rebuilt = out.read_bytes()
            rebuilt_by = _by_session(_rows(out))
        except (ValueError, OSError, _Refused):
            rebuilt = None
        finally:
            os.chdir(here)
    else:
        whole: list[bytes] = []
        for key, raws in stored_by.items():
            dest = tmp / f"s{len(whole)}"
            dest.mkdir(parents=True)
            preds = dest / bundle.LIMITS_FILE
            preds.write_text("".join(r + "\n" for r in raws), encoding="utf-8", newline="\n")
            shas = [json.loads(r).get("record") for r in raws]
            rec = Path(f"{preds}.record")
            rec.mkdir()
            for s in shas:
                src = Path(f"{stored_path}.record") / f"{s}.json"
                if isinstance(s, str) and src.is_file():
                    shutil.copyfile(src, rec / f"{s}.json")
            match, data = _replay(preds, dest / "out" / preds.name)
            whole.append(data or b"")
            if match and data is not None:
                rebuilt_by[key] = [t for t in data.decode("utf-8").split("\n") if t.strip()]
        rebuilt = b"".join(whole) if all(whole) else None
    _emit("stage", name="rebuild")
    order = list(labels)  # the map's own order: race day, heat before feature
    matched = 0
    for key in order:
        if key not in stored_by and key not in rebuilt_by:
            continue
        ok = stored_by.get(key) == rebuilt_by.get(key)
        matched += ok
        lab = labels[key]
        _emit(
            "line",
            id=lab["label"],
            race=lab["race"],
            session=lab["session"],
            lines=len(stored_by.get(key, [])),
            match=ok,
            record=_sha("".join(r + "\n" for r in stored_by.get(key, [])).encode("utf-8")),
        )
    sessions = len([k for k in order if k in stored_by or k in rebuilt_by])
    match = rebuilt == stored and matched == sessions
    _emit("stage", name="seal")
    result: dict[str, Any] = {
        "id": "limits",
        "mode": mode,
        "match": match,
        "sessions": sessions,
        "matched": matched,
        "record_shipped": _sha(stored),
        "record_rebuilt": _sha(rebuilt),
        "seconds": round(time.monotonic() - t0, 2),
    }
    if not match:
        result["why"] = NOT_REBUILT
    _emit("result", **result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="replay_one", description=__doc__.splitlines()[0])
    ap.add_argument("--racing", type=Path, required=True, help="the racing record folder")
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--protest", help="one protest id")
    which.add_argument("--limits", action="store_true", help="the incident-limit lines")
    args = ap.parse_args(argv)
    _emit("stage", name="start")
    for name in (pitbot.FRAMES_DIR_ENV, pitbot.LEDGER_DIR_ENV):
        os.environ.pop(name, None)
    racing = Path(args.racing).resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="faultline-racing-") as tmp:
            if args.limits:
                return limits(racing, Path(tmp))
            return protest(racing, str(args.protest), Path(tmp))
    except _Refused as exc:
        _emit("error", message=str(exc))
        return 2
    except (OSError, json.JSONDecodeError):
        _emit("error", message="the racing record could not be read.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
