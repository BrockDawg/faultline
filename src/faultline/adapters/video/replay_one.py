"""One replay for the live page's worker, in a process of its own.

    python -m faultline.adapters.video.replay_one --record <root> --entry <clip id or entry id>
    python -m faultline.adapters.video.replay_one --record <root> --all <preds.jsonl>
    python -m faultline.adapters.video.replay_one --wait

Each prints one JSON line per event on stdout:
    {"event": "stage", "name": "start|record|rebuild|seal"}
    {"event": "line", "id": ..., "match": ..., "record": ...}      (--all only, one per clip)
    {"event": "result", "id": ..., "record_shipped": ..., "record_rebuilt": ..., "match": ...,
     "rulings": [{"rule": ..., "verdict": ...}], "seconds": ..., "set_sha256": ...}
    {"event": "error", "message": "plain words"}

The stages are printed where the code passes them: the process is up and holds the job (start),
the entry's record was read (record), `cli.replay_line` returned (rebuild), and the rebuilt bytes
were compared with the record (seal). Never on a timer.

`--wait` is the worker's warm spare: the imports are done, it prints {"event": "ready"} and waits
on stdin for one job, {"record": <root>, "entry": <id>} or {"record": <root>, "all": <preds>}.
One job per process, because `perception.RECORD` is a module global.

`perception.RECORD` is set from the job's record root before any read: `cli.replay_record_root`
would otherwise fall back to <repo>/record. A record that cannot be read whole (a blob missing, a
read-only root the replay would have to write into) is an `error` naming the clip, never a
mismatch. The detail goes to stderr for the worker's log; it never reaches the page.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from faultline.adapters.video import cli, perception, record

EXIT_MATCH, EXIT_MISMATCH, EXIT_ERROR = 0, 1, 2


class ReplayError(Exception):
    """A replay that could not run to the end; its message is plain words for the page."""


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True), flush=True)


def _read_lines(preds: Path) -> list[dict]:
    raw = preds.read_bytes().replace(b"\r\n", b"\n")
    return [json.loads(s) for s in raw.decode("utf-8").splitlines() if s.strip()]


def _find(lines: list[dict], key: str) -> dict:
    for old in lines:
        if key in (old.get("id"), old.get("entry")):
            return old
    raise ReplayError(f"{key} is not in this record")


def _rulings(line_bytes: str) -> list[dict]:
    return [
        {"rule": r.get("rule"), "verdict": r.get("verdict")}
        for r in json.loads(line_bytes).get("rulings", [])
    ]


def _replay(old: dict, cache: dict) -> tuple[str, list[str]]:
    """`cli.replay_line` for one line; anything that stops it is a plain error naming the clip."""
    clip = str(old.get("id"))
    try:
        return cli._retry_memory(lambda: cli.replay_line(old, cache), clip)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        traceback.print_exc(file=sys.stderr)
        raise ReplayError(
            f"the record for {clip} could not be read whole on this server, so it was not "
            "rebuilt (no ruling was compared)"
        ) from exc


def run_entry(root: Path, key: str) -> int:
    t0 = time.perf_counter()
    emit("stage", name="start")
    perception.RECORD = root
    old = _find(_read_lines(root / "preds.jsonl"), key)
    clip = str(old.get("id"))
    try:
        record.read_entry(old["entry"])
    except (OSError, ValueError, KeyError) as exc:
        traceback.print_exc(file=sys.stderr)
        raise ReplayError(f"the record for {clip} could not be read on this server") from exc
    emit("stage", name="record")
    s, problems = _replay(old, {})
    emit("stage", name="rebuild")
    for p in problems:
        print(f"{clip}: {p}", file=sys.stderr)
    match = s == cli._dump(old)
    data = s.encode("utf-8")
    emit("stage", name="seal")
    emit(
        "result",
        id=clip,
        record_shipped=old.get("record"),
        record_rebuilt=json.loads(s).get("record"),
        match=match,
        rulings=_rulings(s),
        problems=problems,
        seconds=round(time.perf_counter() - t0, 2),
        set_sha256=record.sha_bytes(data),
    )
    return EXIT_MATCH if match else EXIT_MISMATCH


def run_all(root: Path, preds: Path) -> int:
    """The shipped-set replay: the same per-line rebuild and the same set hash as
    `faultline-video replay` (`cli._replay`): every rebuilt line joined, sha256 of the bytes."""
    t0 = time.perf_counter()
    emit("stage", name="start")
    perception.RECORD = root
    lines = _read_lines(preds)
    for old in lines:
        try:
            record.read_entry(old["entry"])
        except (OSError, ValueError, KeyError) as exc:
            traceback.print_exc(file=sys.stderr)
            raise ReplayError(
                f"the record for {old.get('id')} could not be read on this server"
            ) from exc
    emit("stage", name="record")
    cache: dict = {}
    buf, same, problems = [], 0, []
    for old in lines:
        s, p = _replay(old, cache)
        problems += [f"{old.get('id')}: {x}" for x in p]
        ok = s == cli._dump(old)
        same += ok
        buf.append(s)
        emit("line", id=old.get("id"), match=ok, record=json.loads(s).get("record"))
    emit("stage", name="rebuild")
    for p in problems:
        print(p, file=sys.stderr)
    data = "".join(buf).encode("utf-8")
    shipped = preds.read_bytes().replace(b"\r\n", b"\n")
    match = same == len(lines)
    emit("stage", name="seal")
    emit(
        "result",
        id=root.name,  # the set is named by its record root: shipped, graded or real
        lines=len(lines),
        same=same,
        record_shipped=record.sha_bytes(shipped),
        record_rebuilt=record.sha_bytes(data),
        match=match,
        rulings=[],
        problems=problems,
        seconds=round(time.perf_counter() - t0, 2),
        set_sha256=record.sha_bytes(data),
    )
    return EXIT_MATCH if match else EXIT_MISMATCH


def run_job(job: dict) -> int:
    try:
        root = Path(job["record"])
        if job.get("all"):
            return run_all(root, Path(job["all"]))
        return run_entry(root, str(job["entry"]))
    except ReplayError as exc:
        emit("error", message=str(exc))
        return EXIT_ERROR
    except Exception:  # noqa: BLE001  (the page gets plain words; the log gets the trace)
        traceback.print_exc(file=sys.stderr)
        emit("error", message="the replay stopped on an error on this server")
        return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m faultline.adapters.video.replay_one")
    ap.add_argument("--record", help="the record root: holds entries/, blobs/, clips/")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--entry", help="a clip id or entry id from <record>/preds.jsonl")
    g.add_argument("--all", help="a preds file: replay every line and its set hash")
    g.add_argument("--wait", action="store_true", help="warm spare: one job as JSON on stdin")
    a = ap.parse_args(argv)
    if a.wait:
        emit("ready")
        raw = sys.stdin.readline()
        if not raw.strip():
            return EXIT_ERROR  # the worker closed the spare without a job
        try:
            job = json.loads(raw)
        except json.JSONDecodeError:
            emit("error", message="the replay was handed a job it could not read")
            return EXIT_ERROR
        return run_job(job)
    if not a.record:
        ap.error("--record is required with --entry or --all")
    job = {"record": a.record, "entry": a.entry} if a.entry else {"record": a.record, "all": a.all}
    return run_job(job)


if __name__ == "__main__":
    sys.exit(main())
