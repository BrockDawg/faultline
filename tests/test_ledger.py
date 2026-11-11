"""Tests for the reply ledger in `faultline.ledger`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from faultline.ledger import Ledger, LedgerError, canonical_json, sha256_text

MODEL = "test-model-1"
PARAMS: dict[str, Any] = {"max_tokens": 4000, "temperature": 0.0}
PROMPT = "Read the frames.\nRequest reference: r7-run1"
IMAGES = [sha256_text("frame-a"), sha256_text("frame-b")]


def make_entry(reply: str = '{"verdict": "no_action"}', **overrides: object) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "model": MODEL,
        "params": dict(PARAMS),
        "prompt_sha": sha256_text(PROMPT),
        "image_shas": list(IMAGES),
        "reply": reply,
        "usage": {"prompt_tokens": 1200, "completion_tokens": 80},
    }
    entry.update(overrides)
    return entry


def test_cold_start_twin_put_then_get_then_reopen(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    ledger = Ledger(root)
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    assert ledger.get(key) is None
    assert list(ledger.entries()) == []
    assert not root.exists()

    ledger.put(key, make_entry())
    assert ledger.get(key) == make_entry()
    assert ledger.require(key) == make_entry()

    reopened = Ledger(root)
    assert reopened.get(key) == make_entry()
    assert list(reopened.entries()) == [make_entry()]

    script = (
        "import json, sys\n"
        "from faultline.ledger import Ledger\n"
        "print(json.dumps(Ledger(sys.argv[1]).require(sys.argv[2]), sort_keys=True))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script, str(root), key],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(done.stdout) == make_entry()


def test_file_is_sorted_utf8_with_lf_and_no_temp_left(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    ledger.put(key, make_entry(reply="Kurve é — ok"))
    raw = (tmp_path / f"{key}.json").read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    text = raw.decode("utf-8")
    assert "é —" in text
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{key}.json"]


def test_same_entry_again_is_a_no_op(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    ledger.put(key, make_entry())
    before = (tmp_path / f"{key}.json").read_bytes()
    ledger.put(key, make_entry())
    assert (tmp_path / f"{key}.json").read_bytes() == before


def test_refuses_to_overwrite_a_different_entry(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    ledger.put(key, make_entry())
    with pytest.raises(LedgerError, match="already holds a different entry") as caught:
        ledger.put(key, make_entry(reply="something else"))
    assert key in str(caught.value)
    assert ledger.require(key) == make_entry()


def test_require_missing_names_the_key(tmp_path: Path) -> None:
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    with pytest.raises(LedgerError) as caught:
        Ledger(tmp_path / "empty").require(key)
    assert key in str(caught.value)


def test_key_is_sha256_hex_and_stable() -> None:
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    assert len(key) == 64 and key == key.lower()
    assert key == Ledger.key(MODEL, {"temperature": 0.0, "max_tokens": 4000}, PROMPT, IMAGES)
    assert key == Ledger.key(MODEL, PARAMS, PROMPT, tuple(IMAGES))


@pytest.mark.parametrize(
    ("model", "params", "prompt", "images"),
    [
        ("test-model-2", PARAMS, PROMPT, IMAGES),
        (MODEL, {**PARAMS, "temperature": 0.2}, PROMPT, IMAGES),
        (MODEL, {**PARAMS, "seed": 1}, PROMPT, IMAGES),
        (MODEL, PARAMS, PROMPT.replace("run1", "run2"), IMAGES),
        (MODEL, PARAMS, PROMPT + "-arm2", IMAGES),
        (MODEL, PARAMS, PROMPT, list(reversed(IMAGES))),
        (MODEL, PARAMS, PROMPT, IMAGES[:1]),
        (MODEL, PARAMS, PROMPT, [*IMAGES, sha256_text("frame-c")]),
    ],
)
def test_key_changes_when_any_input_changes(
    model: str, params: dict[str, Any], prompt: str, images: list[str]
) -> None:
    assert Ledger.key(model, params, prompt, images) != Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)


def test_entries_yield_in_sorted_key_order(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    keys = []
    for run in range(1, 6):
        prompt = PROMPT.replace("run1", f"run{run}")
        key = Ledger.key(MODEL, PARAMS, prompt, IMAGES)
        ledger.put(key, make_entry(reply=f"reply {run}", prompt_sha=sha256_text(prompt)))
        keys.append(key)
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    got = list(ledger.entries())
    by_key = {k: ledger.require(k) for k in keys}
    assert got == [by_key[k] for k in sorted(keys)]
    assert sum(e["usage"]["prompt_tokens"] for e in got) == 5 * 1200


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"usage": {"prompt_tokens": 1, "completion_tokens": -1}}, "completion_tokens"),
        ({"usage": {"prompt_tokens": True, "completion_tokens": 1}}, "prompt_tokens"),
        ({"usage": {"prompt_tokens": 1}}, "completion_tokens"),
        ({"prompt_sha": "abc"}, "prompt_sha"),
        ({"image_shas": ["X" * 64]}, "image_shas"),
        ({"reply": None}, "reply"),
        ({"model": ""}, "model"),
        ({"params": {"temperature": float("nan")}}, "non-finite"),
    ],
)
def test_put_refuses_a_malformed_entry(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    with pytest.raises(LedgerError, match=message):
        Ledger(tmp_path).put(key, make_entry(**overrides))
    assert list(tmp_path.iterdir()) == []


def test_put_refuses_a_missing_field(tmp_path: Path) -> None:
    entry = make_entry()
    del entry["usage"]
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    with pytest.raises(LedgerError, match="'usage' is missing"):
        Ledger(tmp_path).put(key, entry)


def test_bad_keys_are_refused(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path)
    for bad in ("../escape", "A" * 64, "abc"):
        with pytest.raises(LedgerError, match="64 lower-case hex"):
            ledger.get(bad)
    with pytest.raises(LedgerError, match="image_shas"):
        Ledger.key(MODEL, PARAMS, PROMPT, ["not-a-sha"])
    with pytest.raises(LedgerError, match="canonical JSON"):
        Ledger.key(MODEL, {"x": float("inf")}, PROMPT, IMAGES)


@pytest.mark.parametrize(
    "params",
    [
        {1: "x"},
        {True: 1},
        {None: 1},
        {"outer": {2: "y"}},
        {"outer": [{"ok": 1}, {False: 0}]},
    ],
)
def test_non_string_dict_keys_are_refused_at_any_depth(
    tmp_path: Path, params: dict[Any, Any]
) -> None:
    with pytest.raises(LedgerError, match="non-string object key"):
        canonical_json(params)
    with pytest.raises(LedgerError, match="non-string object key"):
        Ledger.key(MODEL, params, PROMPT, IMAGES)
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    with pytest.raises(LedgerError, match=f"entry for key {key}.*non-string object key"):
        Ledger(tmp_path).put(key, make_entry(params=params))
    assert list(tmp_path.iterdir()) == []


def test_int_and_string_keys_never_share_a_key() -> None:
    assert canonical_json({"1": "x"}) == '{"1":"x"}'
    with pytest.raises(LedgerError):
        Ledger.key(MODEL, {1: "x"}, PROMPT, IMAGES)


def test_temp_names_are_unique_in_one_process_and_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path] = []
    real_replace = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        seen.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    ledger = Ledger(tmp_path)
    for run in range(1, 4):
        prompt = PROMPT.replace("run1", f"run{run}")
        key = Ledger.key(MODEL, PARAMS, prompt, IMAGES)
        ledger.put(key, make_entry(reply=f"reply {run}", prompt_sha=sha256_text(prompt)))
    assert len(seen) == 3
    pid = str(os.getpid())
    for temp in seen:
        parts = temp.name.split(".")
        assert temp.name.startswith(".") and temp.name.endswith(".tmp")
        assert parts[2] == pid and len(parts[3]) == 16
    same_key_temps = {".".join(t.name.split(".")[3:]) for t in seen}
    assert len(same_key_temps) == 3

    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    stray = tmp_path / f".{key}.{pid}.0123456789abcdef.tmp"
    stray.write_text("{half", encoding="utf-8")
    assert len(list(ledger.entries())) == 3


def test_corrupt_file_is_named(tmp_path: Path) -> None:
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(LedgerError, match="could not be read"):
        Ledger(tmp_path).get(key)


def test_an_absent_count_is_stored_as_null(tmp_path: Path) -> None:
    """A reply with no usage is still recorded, so its spend is counted by the fallback."""
    key = Ledger.key(MODEL, PARAMS, PROMPT, IMAGES)
    usage = {"prompt_tokens": None, "completion_tokens": None}
    stored = Ledger(tmp_path).put(key, make_entry(usage=usage))
    assert stored["usage"] == usage
    assert Ledger(tmp_path).require(key)["usage"] == usage
