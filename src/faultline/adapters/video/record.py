"""The record: every input a ruling used, hashed and kept, so a replay rebuilds the same bytes on
any host.

An entry id is minted from the clip bytes and the window before any model is asked. The record hash
in a ruling line is the sha256 over the sorted "name sha256" lines of every input: clip bytes, the
decoded frames, site values, pack files, hand marks, the measuring constants, the recorded
perception replies, their decoded masks and the pixel facts.

Cross-platform rules (Windows and a Linux container must agree to the byte):
  - every name inside the record is a posix relative name, never a host path;
  - a text file is hashed after CRLF -> LF, so a checkout's line endings never move a hash (binary
    files hash raw);
  - every JSON the record writes is sort_keys, ensure_ascii, "\n" line ends; floats are Python's
    shortest repr;
  - the record is self-contained: site values, pack files, hand marks and constants are
    content-addressed blobs under record/blobs/<sha256>, so a replay needs no host path, no clip, no
    ffmpeg and no network.
  - the clip is hashed twice: "clip" is the mp4 bytes (identity, container metadata included) and
    "frames" is the sha256 of the decoded RGB frames the pixel facts were measured on (kept inside
    the pixel-facts file). A replay never decodes: it reads the pixel facts, so a different ffmpeg
    on the replaying host cannot move a ruling.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
import time
from pathlib import Path

from faultline.adapters.video import measure, perception

VERSION = "faultline 0.4.0"
_TMP_SEQ = itertools.count()
TEXT_SUFFIXES = {".md", ".json", ".txt", ".jsonl", ".sha256", ".yml", ".yaml"}


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    """Raw bytes (the clip, a mask archive)."""
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_text_bytes(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def sha_norm(p: Path) -> str:
    """A text file by its LF-normalised bytes, any other file by its raw bytes."""
    p = Path(p)
    if p.suffix.lower() in TEXT_SUFFIXES:
        return sha_bytes(norm_text_bytes(p.read_bytes()))
    return sha_file(p)


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    """The one JSON form the record hashes: sorted keys, ASCII, no host-dependent whitespace."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def entry_id(clip_sha: str, start_s: float, end_s: float) -> str:
    return "fl-" + hashlib.sha256(f"{clip_sha}:{start_s:.3f}:{end_s:.3f}".encode()).hexdigest()[:12]


def constants() -> dict:
    keys = [
        "SEED",
        "DRAWS",
        "SIGMA_FLOOR_PX",
        "SCALE_SD",
        "SIGMA_TRUCK_FOOT_PX",
        "SIGMA_PERSON_FOOT_PX",
        "AGREE",
        "SG_WIN",
        "STILL_M",
        "BAND",
        "MIN_HEIGHT_PX",
        "MIN_BAND_MASK_PX",
        "VESTED_AT",
        "UNVESTED_BELOW",
        "YG",
        "OR",
        "MIN_VEST_FRAMES",
        "OPERATOR_SHARE",
        "MIN_TRACK_FRAMES",
        "SURROUND_PX",
        "TRUCK_GROW_PX",
        "DIFF_STEP",
        "DIFF_LEVEL",
        "CHANGE_FRAC",
        "CHANGE_FRAMES",
        "STOP_FROM",
        "STOP_TO",
        "MIN_AREA",
        "COLLAPSE",
        "STRIP_HALF_PX",
        "SHOT_CUT_LEVEL",
        "CAMERA_HELD_PX",
        "HELD_MIN_S",
        "COMPENSATE_MAX_PX",
        "MATCH_PEAK_MIN",
        "STILL_SPOTTER_DEFAULT",
        "BG_FAR_PX",
        "BG_RATIO",
    ]
    from faultline.adapters.video import operator as op

    ops = {
        f"operator.{k}": getattr(op, k)
        for k in ("SEAT_LIFT", "SHARE", "RIDE_SD", "RIDE_SD_Y", "MIN_SHARED")
    }
    from faultline.adapters.video import gates

    ops["gates"] = gates.constants()
    return json.loads(
        canon(
            {
                "version": VERSION,
                "OPERATOR_READ": measure.OPERATOR_READ,
                **{k: getattr(measure, k) for k in keys},
                **ops,
            }
        )
    )


def rule_constants() -> dict:
    """The constants that change how measured facts are ruled, not what the pixels say.

    They ride in the ruling's record as their own blob ("rule_constants"), so a change here leaves
    every recorded gate fact and pixel fact key (which hash constants()) unchanged and never forces
    a re-decode."""
    keys = [
        "AWAY_PX",
        "LOAD_PROMPTS",
        "DROP_PX",
        "DROP_FRAMES",
        "DROP_TRUCK_GROW_PX",
        "DROP_AGREE_FRAMES",
        "DROP_MIN_AREA",
        "PAIRING",
        "EDGE_SPEED",
        "UNKNOWN_BOTH_WAYS",
        "CUT_STOP_CHECK",
        "CUT_EDGE_PX",
        "CUT_REVERSE_CHECK",
        "DOCK_CUT_GUARD",
    ]
    from faultline.adapters.video import vest_read

    return json.loads(canon({**{k: getattr(measure, k) for k in keys}, **vest_read.constants()}))


def inputs_hash(inputs: dict[str, str]) -> str:
    lines = "\n".join(f"{k} {v}" for k, v in sorted(inputs.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


# ---------------- content-addressed blobs
def blob_dir() -> Path:
    return perception.RECORD / "blobs"


# bounded: a Windows sharing refusal clears within milliseconds once the other writer is done
BLOB_RETRIES = 50
BLOB_RETRY_S = 0.01


def _sharing_refusal(exc: OSError) -> bool:
    """WinError 5 (access denied: the target is open or mid-replace) or 32 (in use by another
    process).
    """
    return getattr(exc, "winerror", None) in (5, 32) or isinstance(exc, PermissionError)


def _same(p: Path, data: bytes) -> bool:
    try:
        return p.read_bytes() == data
    except OSError:
        return False


def put_blob(data: bytes) -> str:
    """Store LF-normalised text (or JSON) bytes under its own sha256; returns the sha.

    Written once to a temp name of its own (pid, thread, a counter) and moved into place. The name
    is the content's hash, so a writer that finds an identical file already there accepts it and
    drops its temp. On Windows a replace onto a file another writer holds open raises WinError 5 or
    32; that is retried a bounded number of times (BLOB_RETRIES x BLOB_RETRY_S) before it raises."""
    data = norm_text_bytes(data)
    h = sha_bytes(data)
    p = blob_dir() / h
    if _same(p, data):
        return h
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{h}.{os.getpid()}.{threading.get_ident()}.{next(_TMP_SEQ)}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    try:
        for attempt in range(BLOB_RETRIES + 1):
            if _same(p, data):
                return h
            try:
                os.replace(tmp, p)
                return h
            except OSError as exc:
                if not _sharing_refusal(exc) or attempt == BLOB_RETRIES:
                    if _same(p, data):
                        return h
                    raise
                time.sleep(BLOB_RETRY_S)
        return h
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass  # a temp we could not remove is never read: blob names have no suffix


def put_json_blob(obj) -> str:
    return put_blob(canon(obj).encode("utf-8"))


def get_blob(h: str) -> bytes:
    data = norm_text_bytes((blob_dir() / h).read_bytes())
    if sha_bytes(data) != h:
        raise ValueError(f"blob {h[:12]} does not hash to its name")
    return data


def get_json_blob(h: str):
    return json.loads(get_blob(h).decode("utf-8"))


# ---------------- the pack
def pack_files(rules_dir: Path) -> tuple[str, dict[str, Path]]:
    """('file' | 'dir', {posix relative name: path}) for every pack file a judge reads."""
    rules_dir = Path(rules_dir)
    if rules_dir.is_file():
        return "file", {rules_dir.name: rules_dir}
    files = [
        p for p in sorted(rules_dir.rglob("*")) if p.is_file() and p.suffix in (".md", ".json")
    ]
    return "dir", {p.relative_to(rules_dir).as_posix(): p for p in files}


def store_pack(rules_dir: Path) -> dict:
    """{kind, files: {rel: sha}}; every file kept as a blob."""
    kind, files = pack_files(rules_dir)
    return {
        "kind": kind,
        "files": {rel: put_blob(p.read_bytes()) for rel, p in sorted(files.items())},
    }


def pack_inputs_from(pack: dict) -> dict[str, str]:
    return {f"pack/{rel}": h for rel, h in sorted(pack["files"].items())}


def materialise_pack(pack: dict, dest: Path) -> Path:
    """Rebuild the pack from its blobs under dest; returns the path a judge loads (a file or a
    folder).
    """
    dest = Path(dest)
    for rel, h in pack["files"].items():
        p = dest.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(get_blob(h))
    if pack["kind"] == "file":
        return dest / next(iter(pack["files"]))
    return dest


# ---------------- entries
def write_entry(eid: str, manifest: dict) -> Path:
    d = perception.RECORD / "entries"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{eid}.json"
    p.write_text(
        json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return p


def read_entry(eid: str) -> dict:
    return json.loads((perception.RECORD / "entries" / f"{eid}.json").read_text(encoding="utf-8"))


def sha_norm_blob(p: Path) -> str:
    """A blob is always LF-normalised text, whatever its (suffix-less) name."""
    return sha_bytes(norm_text_bytes(Path(p).read_bytes()))
