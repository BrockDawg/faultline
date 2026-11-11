"""Tests for canonical JSON, hashing, bundles and atomic writes in `faultline.record`."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from faultline.record import (
    RecordError,
    bundle_dir,
    canonical,
    file_sha256,
    read_bundle,
    record_hash,
    write_bundle,
    write_lines_atomic,
)

SHA_A = "a" * 64


def test_canonical_bytes_are_sorted_compact_utf8() -> None:
    assert canonical({"b": 1, "a": [1, 2], "c": "é"}) == '{"a":[1,2],"b":1,"c":"é"}'.encode()


def test_same_input_same_hash() -> None:
    inputs = {"subjects": ["7", "12"], "window": [10.5, 14.0], "rule": "S1"}
    assert record_hash(inputs) == record_hash(json.loads(json.dumps(inputs)))


def test_key_order_does_not_change_the_hash() -> None:
    one = {"a": 1, "b": {"x": 1, "y": 2}}
    two = {"b": {"y": 2, "x": 1}, "a": 1}
    assert record_hash(one) == record_hash(two)


def test_hash_is_sha256_of_canonical() -> None:
    value = {"k": "v"}
    assert record_hash(value) == hashlib.sha256(canonical(value)).hexdigest()
    assert len(record_hash(value)) == 64


def test_one_changed_value_changes_the_hash() -> None:
    assert record_hash({"k": "abc"}) != record_hash({"k": "abd"})


def test_canonical_refuses_nan_and_unencodable_values() -> None:
    with pytest.raises(RecordError, match="canonical JSON"):
        canonical({"x": float("nan")})
    with pytest.raises(RecordError, match="canonical JSON"):
        canonical({"x": object()})


@pytest.mark.parametrize(
    "value",
    [
        {1: "x"},
        {True: 1},
        {None: 1},
        {"a": {"b": {2: "x"}}},
        {"a": [{"ok": 1}, {False: 1}]},
        [[{None: "x"}]],
        {"a": ({3: "x"},)},
    ],
)
def test_canonical_refuses_non_string_keys_at_any_depth(value: object) -> None:
    with pytest.raises(RecordError, match="not str"):
        canonical(value)
    with pytest.raises(RecordError, match="not str"):
        record_hash(value)


def test_int_key_does_not_share_a_hash_with_its_string() -> None:
    assert record_hash({"1": "x"})
    with pytest.raises(RecordError):
        record_hash({1: "x"})


def test_bundle_and_lines_refuse_non_string_keys(tmp_path: Path) -> None:
    preds = tmp_path / "preds.jsonl"
    with pytest.raises(RecordError, match="not str"):
        write_bundle(preds, SHA_A, {"a": {1: "x"}})
    with pytest.raises(RecordError, match="preds.jsonl.*not str"):
        write_lines_atomic(preds, [{"ok": 1}, {True: 1}])
    assert list(tmp_path.iterdir()) == []


def test_file_sha256_hashes_bytes_and_one_byte_changes_it(tmp_path: Path) -> None:
    f = tmp_path / "clip.bin"
    f.write_bytes(b"\x00\x01payload")
    first = file_sha256(f)
    assert first == hashlib.sha256(b"\x00\x01payload").hexdigest()
    f.write_bytes(b"\x00\x01paylobd")
    assert file_sha256(f) != first


def test_file_sha256_missing_file_names_it(tmp_path: Path) -> None:
    missing = tmp_path / "nope.bin"
    with pytest.raises(RecordError, match="nope.bin"):
        file_sha256(missing)


def test_bundle_round_trip(tmp_path: Path) -> None:
    preds = tmp_path / "preds.jsonl"
    bundle = {"inputs": {"b": 2, "a": 1}, "hint": "frames/x.jpg"}
    path = write_bundle(preds, SHA_A, bundle)
    assert path == tmp_path / "preds.jsonl.record" / f"{SHA_A}.json"
    assert bundle_dir(preds) == tmp_path / "preds.jsonl.record"
    assert path.read_bytes() == canonical(bundle) + b"\n"
    assert read_bundle(preds, SHA_A) == bundle


def test_bundle_rewrite_same_bytes_is_allowed_different_is_refused(tmp_path: Path) -> None:
    preds = tmp_path / "preds.jsonl"
    write_bundle(preds, SHA_A, {"a": 1})
    write_bundle(preds, SHA_A, {"a": 1})
    with pytest.raises(RecordError, match="different bundle"):
        write_bundle(preds, SHA_A, {"a": 2})
    assert read_bundle(preds, SHA_A) == {"a": 1}


@pytest.mark.parametrize("bad", ["../escape", "A" * 64, "a" * 63, ""])
def test_bundle_refuses_bad_record_id(tmp_path: Path, bad: str) -> None:
    with pytest.raises(RecordError, match="64 lower-case hex"):
        write_bundle(tmp_path / "preds.jsonl", bad, {})
    with pytest.raises(RecordError, match="64 lower-case hex"):
        read_bundle(tmp_path / "preds.jsonl", bad)


def test_read_bundle_missing_and_malformed(tmp_path: Path) -> None:
    preds = tmp_path / "preds.jsonl"
    with pytest.raises(RecordError, match="no bundle"):
        read_bundle(preds, SHA_A)
    folder = bundle_dir(preds)
    folder.mkdir()
    (folder / f"{SHA_A}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RecordError, match="not valid JSON"):
        read_bundle(preds, SHA_A)
    (folder / f"{SHA_A}.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(RecordError, match="JSON object"):
        read_bundle(preds, SHA_A)


def test_write_lines_atomic_writes_sorted_lf_utf8(tmp_path: Path) -> None:
    out = tmp_path / "preds.jsonl"
    write_lines_atomic(out, [{"b": 1, "a": "é"}, {"z": None}])
    assert out.read_bytes() == '{"a":"é","b":1}\n{"z":null}\n'.encode()
    assert list(tmp_path.iterdir()) == [out]


def test_write_lines_atomic_replaces_old_content(tmp_path: Path) -> None:
    out = tmp_path / "preds.jsonl"
    out.write_bytes(b"old\n")
    write_lines_atomic(out, [{"n": 1}])
    assert out.read_bytes() == b'{"n":1}\n'


def _rows_then_crash() -> Iterator[dict[str, int]]:
    yield {"n": 1}
    raise RuntimeError("boom")


def test_atomic_write_leaves_no_file_on_exception(tmp_path: Path) -> None:
    out = tmp_path / "preds.jsonl"
    with pytest.raises(RuntimeError, match="boom"):
        write_lines_atomic(out, _rows_then_crash())
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_keeps_old_content_on_exception(tmp_path: Path) -> None:
    out = tmp_path / "preds.jsonl"
    out.write_bytes(b"old\n")
    with pytest.raises(RecordError, match="preds.jsonl"):
        write_lines_atomic(out, [{"n": 1}, {"bad": float("inf")}])
    assert out.read_bytes() == b"old\n"
    assert list(tmp_path.iterdir()) == [out]


def test_atomic_write_removes_temp_when_the_move_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "preds.jsonl"

    def fail_replace(src: object, dst: object) -> None:
        raise OSError(13, "denied")

    monkeypatch.setattr("faultline.record.os.replace", fail_replace)
    with pytest.raises(RecordError, match="could not be written"):
        write_lines_atomic(out, [{"n": 1}])
    assert list(tmp_path.iterdir()) == []
