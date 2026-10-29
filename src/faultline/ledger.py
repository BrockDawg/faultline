"""The reply ledger: every model reply, stored once under the hash of exactly what was asked.

A key is the sha256 hex of a canonical JSON encoding of four inputs:

- `model`: the model id, a non-empty string;
- `params`: a JSON object of call parameters (temperature, max tokens, schema and so on);
- `prompt_text`: the full prompt text, including any per-run request reference, so two runs
  that differ only by that reference get two keys;
- `image_shas`: the sha256 hex of each image sent, in the order sent (order is part of the key).

The canonical encoding is UTF-8 JSON with sorted keys, no spaces, no NaN or infinity.

Each key is one file, `<root>/<key>.json`, written as UTF-8 JSON with sorted keys, two-space
indent and a closing `\\n`, through a temp file and `os.replace`, so a crash never leaves a
half-written entry (the temp name carries the process id and a random suffix, and
`entries()` never reads it). An entry is a JSON object holding:

- `model` (str), `params` (object), `prompt_sha` (64 lower-case hex of the prompt text),
  `image_shas` (list of 64 lower-case hex), `reply` (str);
- `usage`: `{"prompt_tokens": int, "completion_tokens": int}`, both non-negative.

Other keys are kept as given. `put` refuses to replace an entry with a different one; putting
the same entry again does nothing. `require` is the replay read: a missing key raises
`LedgerError` naming the key. `entries()` yields every stored entry in sorted key order.
Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = ["Ledger", "LedgerError", "canonical_json", "sha256_text"]

_HEX64 = re.compile(r"[0-9a-f]{64}")
_REQUIRED = ("model", "params", "prompt_sha", "image_shas", "reply", "usage")
_USAGE_FIELDS = ("prompt_tokens", "completion_tokens")


class LedgerError(ValueError):
    """The ledger refused a read or write; the message names the key or file and the reason."""


def canonical_json(value: object) -> str:
    """Compact JSON with sorted keys and no NaN or infinity: the bytes a key is hashed from.

    Every object key, at any depth, must already be a string: `json` would quietly turn
    `1`, `True` or `None` into `"1"`, `"true"` or `"null"`, so two different values would
    share one encoding.
    """
    _check_keys(value, "value")
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"value cannot be encoded as canonical JSON ({exc}).") from exc


def sha256_text(text: str) -> str:
    """The sha256 hex of `text` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_hex(value: object, what: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise LedgerError(f"{what} must be 64 lower-case hex characters, got {value!r}.")
    return value


def _check_keys(value: object, what: str) -> None:
    if isinstance(value, Mapping):
        for name, item in value.items():
            if not isinstance(name, str):
                raise LedgerError(
                    f"{what} holds a non-string object key ({name!r}); "
                    "canonical JSON takes string keys only."
                )
            _check_keys(item, what)
    elif isinstance(value, list | tuple):
        for item in value:
            _check_keys(item, what)


def _check_floats(value: object, what: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise LedgerError(f"{what} holds a non-finite number ({value!r}).")
    if isinstance(value, Mapping):
        for item in value.values():
            _check_floats(item, what)
    elif isinstance(value, list | tuple):
        for item in value:
            _check_floats(item, what)


def _check_entry(key: str, entry: object) -> dict[str, Any]:
    where = f"entry for key {key}"
    if not isinstance(entry, Mapping):
        raise LedgerError(f"{where}: must be a JSON object, not {type(entry).__name__}.")
    for field in _REQUIRED:
        if field not in entry:
            raise LedgerError(f"{where}: the required field {field!r} is missing.")
    model = entry["model"]
    if not isinstance(model, str) or not model.strip():
        raise LedgerError(f"{where}: 'model' must be a non-empty string.")
    if not isinstance(entry["params"], Mapping):
        raise LedgerError(f"{where}: 'params' must be a JSON object.")
    _check_hex(entry["prompt_sha"], f"{where}: 'prompt_sha'")
    shas = entry["image_shas"]
    if not isinstance(shas, list | tuple):
        raise LedgerError(f"{where}: 'image_shas' must be a list.")
    for index, sha in enumerate(shas):
        _check_hex(sha, f"{where}: 'image_shas'[{index}]")
    if not isinstance(entry["reply"], str):
        raise LedgerError(f"{where}: 'reply' must be a string.")
    usage = entry["usage"]
    if not isinstance(usage, Mapping):
        raise LedgerError(f"{where}: 'usage' must be a JSON object.")
    for field in _USAGE_FIELDS:
        count = usage.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise LedgerError(
                f"{where}: 'usage'.{field!r} must be a non-negative whole number, got {count!r}."
            )
    _check_keys(entry, where)
    _check_floats(entry, where)
    return json.loads(canonical_json(entry))


class Ledger:
    """A folder of model replies, one JSON file per key. The folder is made on first `put`."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @staticmethod
    def key(
        model: str, params: Mapping[str, Any], prompt_text: str, image_shas: Sequence[str]
    ) -> str:
        """The sha256 hex of the canonical encoding of what was asked. Order of images counts."""
        if not isinstance(model, str) or not model.strip():
            raise LedgerError(f"key: 'model' must be a non-empty string, got {model!r}.")
        if not isinstance(params, Mapping):
            raise LedgerError(f"key: 'params' must be a mapping, not {type(params).__name__}.")
        if not isinstance(prompt_text, str):
            raise LedgerError(f"key: 'prompt_text' must be a string, not {type(prompt_text)}.")
        if isinstance(image_shas, str) or not isinstance(image_shas, Sequence):
            raise LedgerError("key: 'image_shas' must be a list of sha256 hex strings.")
        shas = [_check_hex(sha, f"key: 'image_shas'[{i}]") for i, sha in enumerate(image_shas)]
        payload = {
            "image_shas": shas,
            "model": model,
            "params": dict(params),
            "prompt_text": prompt_text,
        }
        return sha256_text(canonical_json(payload))

    def path(self, key: str) -> Path:
        """The file a key lives in. Refuses anything but 64 lower-case hex."""
        return self.root / f"{_check_hex(key, 'ledger key')}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """The entry stored under `key`, or None when there is none."""
        path = self.path(key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LedgerError(
                f"{path}: the entry for key {key} could not be read ({exc})."
            ) from exc
        if not isinstance(data, dict):
            raise LedgerError(f"{path}: the entry for key {key} is not a JSON object.")
        return data

    def require(self, key: str) -> dict[str, Any]:
        """The entry stored under `key`; raises `LedgerError` naming the key when absent."""
        entry = self.get(key)
        if entry is None:
            raise LedgerError(
                f"the ledger at {self.root} has no entry for key {key}; "
                "a replay can only use replies already recorded."
            )
        return entry

    def put(self, key: str, entry: Mapping[str, Any]) -> dict[str, Any]:
        """Store `entry` under `key` and return it as stored.

        The same entry again is a no-op; a different entry under a stored key raises.
        """
        path = self.path(key)
        clean = _check_entry(key, entry)
        existing = self.get(key)
        if existing is not None:
            if canonical_json(existing) == canonical_json(clean):
                return existing
            raise LedgerError(
                f"{path}: key {key} already holds a different entry; "
                "a recorded reply is never overwritten."
            )
        self.root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(clean, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        temp = self.root / f".{key}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
        return clean

    def entries(self) -> Iterator[dict[str, Any]]:
        """Every stored entry, in sorted key order. A missing folder yields nothing."""
        if not self.root.is_dir():
            return
        keys = sorted(
            p.stem for p in self.root.glob("*.json") if p.is_file() and _HEX64.fullmatch(p.stem)
        )
        for key in keys:
            yield self.require(key)
