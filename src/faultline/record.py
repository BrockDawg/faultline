"""The record: canonical JSON, content hashes, and the bundle written beside an output file.

Contract:

- `canonical(obj)` turns a JSON value into bytes: keys sorted, `(",", ":")` separators,
  `ensure_ascii=False`, UTF-8. The same value always gives the same bytes, whatever the key
  order it was built in. It refuses NaN and infinity, keys that are not strings, and any value
  JSON cannot hold (raises `RecordError`).
- `record_hash(inputs)` is the sha256 hex of `canonical(inputs)`: 64 lower-case hex characters.
  The caller keeps wall-clock time and machine-specific absolute paths out of `inputs`; files
  enter the hash by content (`file_sha256`), and paths ride in the bundle only as hints.
- `file_sha256(path)` is the sha256 hex of a file's bytes.
- `write_bundle(out_path, sha, bundle)` writes `<out_path>.record/<sha>.json`: canonical JSON
  plus one `\\n`, written atomically. It refuses a `sha` that is not 64 lower-case hex, and
  refuses to replace an existing bundle that holds different bytes. Rewriting the same bytes
  is allowed, so a rerun is idempotent. Returns the bundle's path.
- `read_bundle(out_path, sha)` reads that file back as a JSON object.
- `write_lines_atomic(path, rows)` writes one canonical JSON line per row, each ending in
  `\\n`, UTF-8, to a temporary file in the same folder, then moves it over `path` with
  `os.replace`. If anything fails before the move, the temporary file is removed and `path`
  is left as it was (absent, or its old content).

No function here reads the clock or the network. Every failure raises `RecordError`, whose
message names the file (where there is one) and the reason.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = [
    "RecordError",
    "bundle_dir",
    "canonical",
    "file_sha256",
    "read_bundle",
    "record_hash",
    "write_bundle",
    "write_lines_atomic",
]

_SHA_RE = re.compile(r"[0-9a-f]{64}")
_BUNDLE_SUFFIX = ".record"
_CHUNK = 1 << 20


class RecordError(ValueError):
    """A record could not be built, written or read; the message names the file and the reason."""


def _check_keys(obj: Any, where: str) -> None:
    """Raise `RecordError` on any dict key that is not a `str`, at any depth.

    `json.dumps` would quietly turn `1`, `True` or `None` keys into strings, so two different
    values would share one hash.
    """
    stack: list[tuple[Any, str]] = [(obj, where)]
    while stack:
        value, at = stack.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise RecordError(
                        f"value cannot be written as canonical JSON (key {key!r} at {at} "
                        f"is {type(key).__name__}, not str)."
                    )
                stack.append((item, f"{at}[{key!r}]"))
        elif isinstance(value, (list, tuple)):
            stack.extend((item, f"{at}[{i}]") for i, item in enumerate(value))


def canonical(obj: Any) -> bytes:
    """Return the canonical UTF-8 JSON bytes of `obj`: sorted keys, no spaces, no ASCII escapes."""
    _check_keys(obj, "$")
    try:
        text = json.dumps(
            obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise RecordError(f"value cannot be written as canonical JSON ({exc}).") from exc
    return text.encode("utf-8")


def record_hash(inputs: Any) -> str:
    """Return the sha256 hex of `canonical(inputs)`."""
    return hashlib.sha256(canonical(inputs)).hexdigest()


def file_sha256(path: Path | str) -> str:
    """Return the sha256 hex of the bytes of the file at `path`."""
    p = Path(path)
    digest = hashlib.sha256()
    try:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RecordError(f"{p}: could not be read ({exc.strerror or exc}).") from exc
    return digest.hexdigest()


def bundle_dir(out_path: Path | str) -> Path:
    """Return the bundle folder that sits beside `out_path`: `<out_path>.record`."""
    return Path(str(out_path) + _BUNDLE_SUFFIX)


def _bundle_path(out_path: Path | str, sha: str) -> Path:
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        raise RecordError(
            f"{bundle_dir(out_path)}: record id {sha!r} is not 64 lower-case hex characters."
        )
    return bundle_dir(out_path) / f"{sha}.json"


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write `data` to a temporary file beside `path`, then move it over `path`."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        raise RecordError(f"{path}: could not be written ({exc.strerror or exc}).") from exc
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise RecordError(f"{path}: could not be written ({exc.strerror or exc}).") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_bundle(out_path: Path | str, sha: str, bundle: Any) -> Path:
    """Write `bundle` to `<out_path>.record/<sha>.json` and return that path.

    Refuses to replace an existing bundle whose bytes differ: one record id names one bundle.
    """
    path = _bundle_path(out_path, sha)
    data = canonical(bundle) + b"\n"
    if path.exists():
        try:
            old = path.read_bytes()
        except OSError as exc:
            raise RecordError(f"{path}: could not be read ({exc.strerror or exc}).") from exc
        if old == data:
            return path
        raise RecordError(f"{path}: already holds a different bundle for this record id.")
    _write_bytes_atomic(path, data)
    return path


def read_bundle(out_path: Path | str, sha: str) -> dict[str, Any]:
    """Read `<out_path>.record/<sha>.json` back as a JSON object."""
    path = _bundle_path(out_path, sha)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RecordError(f"{path}: no bundle for this record id.") from exc
    except OSError as exc:
        raise RecordError(f"{path}: could not be read ({exc.strerror or exc}).") from exc
    except UnicodeDecodeError as exc:
        raise RecordError(f"{path}: is not valid UTF-8 text.") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecordError(
            f"{path}: is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})."
        ) from exc
    if not isinstance(data, dict):
        raise RecordError(f"{path}: must hold a JSON object, not {type(data).__name__}.")
    return data


def write_lines_atomic(path: Path | str, rows: Iterable[Any]) -> Path:
    """Write one canonical JSON line per row to `path`, atomically, and return the path.

    The rows are all encoded before anything is written, so a row that cannot be encoded (or an
    iterable that raises) leaves `path` untouched.
    """
    p = Path(path)
    try:
        data = b"".join(canonical(row) + b"\n" for row in rows)
    except RecordError as exc:
        raise RecordError(f"{p}: {exc}") from exc
    _write_bytes_atomic(p, data)
    return p
