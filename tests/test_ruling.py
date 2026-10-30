"""Tests for faultline.ruling: a fake transport only, never a real network call."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx
import pytest

from faultline import client, ruling
from faultline.ledger import Ledger
from faultline.lint import LintError

MODEL = "muse-spark-1.3"
CANDIDATES = ["7", "12", "33"]
FRAMES = ruling.label_frames([120.0, 120.5, 121.0])
LABELS = [label for label, _ in FRAMES]
NAMES = ["Quillon Ostrava", "Verna Talbrook"]  # invented
RULE_TEXT = (
    "9.2 A driver who causes avoidable contact may be penalised.\n"
    "9.5 The stewards choose the penalty from the guide."
)
FACTS = [
    "The gap between 7 and 12 closed from 4.0 metres to 0.0 metres within 1.5 seconds.",
    "The counter for 12 rose by 4 at second 120.",
]
REPORT = "12 says 7 hit the rear at the hairpin and spun them."
IMAGES = [b"\xff\xd8fake-frame-1\xff\xd9", b"\xff\xd8fake-frame-2\xff\xd9"]
REASON = "Rule 9.2: frame 2 shows the front of 7 meeting the rear of 12 under braking."
# The caller's words (an adapter supplies them; the core holds none).
VERDICTS = ruling.Verdicts(
    (
        ("penalty", "the rules hold one named car responsible and call for a penalty."),
        ("racing_incident", "the rules hold no single car responsible."),
        ("no_action", "the rules call for no action on this protest."),
        ("not_visible", "the frames do not show the moment well enough to rule."),
    ),
    naming="penalty",
)
WORDING = ruling.Wording(role="a steward", document="protest")


class SchemaError(ValueError):
    """A value broke the schema (the test-local checker; jsonschema is not a dependency)."""


_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "null": type(None),
}


def check(value: Any, sch: dict[str, Any], at: str = "$") -> None:
    """Check `value` against the schema subset `ruling.schema` uses; raise SchemaError."""
    allowed = set(sch) - {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "anyOf",
        "enum",
        "pattern",
        "minLength",
        "maxLength",
        "items",
    }
    assert not allowed, f"unchecked schema keywords at {at}: {allowed}"
    if "anyOf" in sch:
        for option in sch["anyOf"]:
            try:
                check(value, option, at)
                return
            except SchemaError:
                continue
        raise SchemaError(f"{at}: no anyOf option matches")
    kind = sch.get("type")
    if kind is not None and not isinstance(value, _TYPES[kind]):
        raise SchemaError(f"{at}: not {kind}")
    if "enum" in sch and value not in sch["enum"]:
        raise SchemaError(f"{at}: not in enum")
    if "pattern" in sch and not re.search(sch["pattern"], value):
        raise SchemaError(f"{at}: pattern")
    if "minLength" in sch and len(value) < sch["minLength"]:
        raise SchemaError(f"{at}: too short")
    if "maxLength" in sch and len(value) > sch["maxLength"]:
        raise SchemaError(f"{at}: too long")
    if kind == "object":
        props = sch.get("properties", {})
        missing = set(sch.get("required", [])) - set(value)
        if missing:
            raise SchemaError(f"{at}: missing {sorted(missing)}")
        if sch.get("additionalProperties") is False and set(value) - set(props):
            raise SchemaError(f"{at}: extra keys")
        for name, item in value.items():
            if name in props:
                check(item, props[name], f"{at}.{name}")
    if kind == "array":
        for i, item in enumerate(value):
            check(item, sch.get("items", {}), f"{at}[{i}]")


def reply(offender: str | None = "7", verdict: str = "penalty", **extra: Any) -> str:
    body = {"offender": offender, "verdict": verdict, "reason": REASON, "frames_used": ["frame 2"]}
    body.update(extra)
    return json.dumps(body)


class Scripted:
    """A fake transport answering each call with the next scripted reply text."""

    def __init__(self, texts: list[str], cache: list[str | None] | None = None) -> None:
        self.texts = list(texts)
        self.cache = list(cache or [])
        self.usage: dict[str, int] | None = {"prompt_tokens": 900, "completion_tokens": 120}
        self.calls: list[dict[str, Any]] = []
        self._http = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        index = len(self.calls) - 1
        text = self.texts[index]
        word = self.cache[index] if index < len(self.cache) else "miss"
        return httpx.Response(
            200,
            headers={client.CACHE_HEADER: word} if word is not None else None,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": self.usage,
            },
        )

    def __call__(self, url: str, headers: dict[str, str], payload: dict[str, Any]):
        self.calls.append(payload)
        return self._http.post(url, headers=headers, json=payload)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for name in ("MODEL_API_KEY", "MODEL_API_BASE", "FAULTLINE_FAKE_MODEL", "FAULTLINE_CAP_USD"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "MODEL_API_KEY=test-key-not-real\nMODEL_API_BASE=http://127.0.0.1:9/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STEWARD_ENV_FILE", str(env_file))
    return env_file


def install(
    monkeypatch: pytest.MonkeyPatch, texts: list[str], cache: list[str | None] | None = None
) -> Scripted:
    fake = Scripted(texts, cache)
    monkeypatch.setattr(client, "CLIENT", fake)
    return fake


def prompt() -> str:
    return ruling.build_prompt(
        RULE_TEXT, FACTS, CANDIDATES, REPORT, FRAMES, "car", VERDICTS, WORDING
    )


def do_read(ledger: Ledger, **kw: Any) -> ruling.ModelRead:
    args: dict[str, Any] = {
        "candidates": CANDIDATES,
        "frame_labels": LABELS,
        "names": NAMES,
        "verdicts": VERDICTS,
    }
    args.update(kw)
    return ruling.read(prompt(), IMAGES, MODEL, ledger, "r15", **args)


# ------------------------------------------------------------------------------- validate


def test_reply_naming_a_subject_outside_the_set_is_rejected() -> None:
    assert ruling.validate(reply("7"), CANDIDATES, LABELS, VERDICTS) is not None
    assert ruling.validate(reply("99"), CANDIDATES, LABELS, VERDICTS) is None
    assert ruling.validate(reply(None, "not_visible"), CANDIDATES, LABELS, VERDICTS) is not None


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "[]",
        reply("7", "guilty"),
        reply("7", reason="too short"),
        reply("7", reason="x" * 601),
        reply("7", frames_used=["frame 9"]),
        reply("7", extra_key=1),
        json.dumps({"offender": "7", "verdict": "penalty", "reason": REASON}),
        reply(7),  # type: ignore[arg-type]
    ],
)
def test_validate_refuses_bad_replies(text: str) -> None:
    assert ruling.validate(text, CANDIDATES, LABELS, VERDICTS) is None


def test_a_penalty_with_no_offender_is_a_failed_run() -> None:
    assert ruling.validate(reply(None, "penalty"), CANDIDATES, LABELS, VERDICTS) is None


@pytest.mark.parametrize("verdict", ["racing_incident", "no_action", "not_visible"])
def test_an_offender_without_a_penalty_is_a_failed_run(verdict: str) -> None:
    assert ruling.validate(reply("7", verdict), CANDIDATES, LABELS, VERDICTS) is None
    assert ruling.validate(reply(None, verdict), CANDIDATES, LABELS, VERDICTS) is not None


def test_validate_tolerates_a_fenced_block() -> None:
    text = "Here is my ruling.\n```json\n" + reply("12") + "\n```\n"
    got = ruling.validate(text, CANDIDATES, LABELS, VERDICTS)
    assert got is not None and got["offender"] == "12" and got["verdict"] == "penalty"


# ------------------------------------------------------------------------------- schema


@pytest.mark.parametrize("enum", [True, False])
def test_enum_and_pattern_schemas_both_validate(enum: bool) -> None:
    sch = ruling.schema(CANDIDATES, VERDICTS, enum=enum)
    assert sch["additionalProperties"] is False and sch["required"] == list(ruling.REPLY_KEYS)
    check(json.loads(reply("7")), sch)
    check(json.loads(reply(None, "no_action")), sch)
    with pytest.raises(SchemaError):
        check(json.loads(reply("7", "guilty")), sch)
    # Length keywords are never sent (A5 sent none); validate checks the reason's length.
    assert set(sch["properties"]["reason"]) == {"type"}


def test_enum_schema_refuses_outside_the_set_and_pattern_refuses_non_digits() -> None:
    with pytest.raises(SchemaError):
        check(json.loads(reply("99")), ruling.schema(CANDIDATES, VERDICTS))
    check(json.loads(reply("99")), ruling.schema(CANDIDATES, VERDICTS, enum=False))
    with pytest.raises(SchemaError):
        check(json.loads(reply("7a")), ruling.schema(CANDIDATES, VERDICTS, enum=False))


def test_fake_model_seam_fills_the_enum_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    got = client.chat(
        [{"role": "user", "content": "x"}],
        MODEL,
        schema=ruling.schema(CANDIDATES, VERDICTS),
        spent_entries=[],
    )
    sch = ruling.schema(CANDIDATES, VERDICTS)
    check(json.loads(got.text), sch)


# ------------------------------------------------------------------------------- prompt


def test_prompt_holds_every_section_and_passes_the_lint() -> None:
    text = prompt()
    for part in (RULE_TEXT.splitlines()[0], FACTS[0], REPORT, "7, 12, 33"):
        assert part in text
    assert "frame 1: stream second 120.0" in text and "frame 3: stream second 121.0" in text
    for verdict in VERDICTS.labels:
        assert verdict in text
    from faultline.lint import assert_clean

    assert_clean(text + "\n\n" + ruling.run_reference("r15", 3), NAMES)


def test_prompt_never_says_no_contact_means_no_action() -> None:
    text = prompt().casefold()
    for sentence in re.split(r"[.\n]", text):
        assert not ("contact" in sentence and re.search(r"no[ _]action", sentence)), sentence
    # The scaffolding alone (no caller text) never mentions contact at all.
    plain = ruling.Verdicts((("yes", "it is so."), ("no", "it is not.")), naming="yes")
    words = ruling.Wording(role="a judge", document="report")
    bare = ruling.build_prompt(
        "Rule one.", [], ["1"], "A report.", [], "unit", plain, words
    ).casefold()
    assert "contact" not in bare


def test_a_planted_name_raises_before_any_call(monkeypatch, env, tmp_path) -> None:
    fake = install(monkeypatch, [reply()] * 3)
    planted = ruling.build_prompt(
        RULE_TEXT, FACTS, CANDIDATES, REPORT + " Ostrava braked late.", FRAMES, "car",
        VERDICTS, WORDING,
    )  # fmt: skip
    with pytest.raises(LintError):
        ruling.read(
            planted,
            IMAGES,
            MODEL,
            Ledger(tmp_path / "ledger"),
            "r15",
            candidates=CANDIDATES,
            frame_labels=LABELS,
            names=NAMES,
            verdicts=VERDICTS,
        )
    assert fake.calls == []


# ------------------------------------------------------------------------------- read


def test_three_of_three_agree(monkeypatch, env, tmp_path) -> None:
    install(monkeypatch, [reply("7")] * 3)
    got = do_read(Ledger(tmp_path / "ledger"))
    assert got.as_dict() == {
        "model": MODEL,
        "runs": 3,
        "agreed": True,
        "verdict": "penalty",
        "offender": "7",
        "reason": REASON,
        "parse_failures": 0,
        "lint_hits": 0,
        "source": "model",
    }


def test_two_of_three_is_not_agreed(monkeypatch, env, tmp_path) -> None:
    install(monkeypatch, [reply("7"), reply("7"), reply("12")])
    got = do_read(Ledger(tmp_path / "ledger"))
    assert got.agreed is False and got.offender is None and got.verdict is None
    assert got.parse_failures == 0


def test_same_offender_other_verdict_is_not_agreed(monkeypatch, env, tmp_path) -> None:
    install(monkeypatch, [reply("7"), reply("7"), reply("7", "racing_incident")])
    assert do_read(Ledger(tmp_path / "ledger")).agreed is False


def test_a_parse_failure_is_a_failed_run(monkeypatch, env, tmp_path) -> None:
    install(monkeypatch, [reply("7"), "I think 7 did it.", reply("7")])
    got = do_read(Ledger(tmp_path / "ledger"))
    assert got.agreed is False and got.offender is None and got.parse_failures == 1


def test_an_outside_offender_is_a_failed_run(monkeypatch, env, tmp_path) -> None:
    install(monkeypatch, [reply("99")] * 3)
    got = do_read(Ledger(tmp_path / "ledger"))
    assert got.agreed is False and got.parse_failures == 3


def test_nonce_differs_per_run_and_enters_the_ledger_key(monkeypatch, env, tmp_path) -> None:
    fake = install(monkeypatch, [reply()] * 3)
    got = do_read(Ledger(tmp_path / "ledger"))
    tails = []
    for k, payload in enumerate(fake.calls, start=1):
        parts = payload["messages"][-1]["content"]
        texts = [p["text"] for p in parts if p["type"] == "text"]
        assert texts[-1] == f"Request reference: r15-run{k}"
        assert [p["type"] for p in parts[len(texts) :]] == ["image_url"] * len(IMAGES)
        tails.append(texts[-1])
    assert len(set(tails)) == 3
    assert len(set(got.keys)) == 3
    shas = [hashlib.sha256(b).hexdigest() for b in IMAGES]
    params = client.request_params(
        MODEL, ruling.schema(CANDIDATES, VERDICTS), ruling.DEFAULT_MAX_TOKENS
    )
    for k, key in enumerate(got.keys, start=1):
        full = prompt() + "\n\n" + ruling.run_reference("r15", k)
        assert key == Ledger.key(MODEL, params, full, shas)
    assert got.sent_refs == ("r15-run1", "r15-run2", "r15-run3")


def test_a_full_ledger_sends_nothing_and_gives_the_same_read(monkeypatch, env, tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger")
    install(monkeypatch, [reply(None, "racing_incident")] * 3)
    first = do_read(ledger)
    again = install(monkeypatch, [])
    second = do_read(ledger)
    assert again.calls == []
    assert second.as_dict() == first.as_dict()
    assert second.sent_refs == ()
    assert len(list(ledger.entries())) == 3


def test_json_mode_sends_the_strict_schema_and_no_json_mode_sends_none(
    monkeypatch, env, tmp_path
) -> None:
    fake = install(monkeypatch, [reply()] * 6)
    do_read(Ledger(tmp_path / "a"))
    rf = fake.calls[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == ruling.schema(CANDIDATES, VERDICTS)
    off = install(monkeypatch, ["```json\n" + reply() + "\n```"] * 3)
    got = do_read(Ledger(tmp_path / "b"), json_mode=False, max_tokens=12000)
    assert all("response_format" not in c for c in off.calls)
    assert got.agreed is True


def test_pattern_schema_can_be_sent(monkeypatch, env, tmp_path) -> None:
    fake = install(monkeypatch, [reply()] * 3)
    do_read(Ledger(tmp_path / "ledger"), schema=ruling.schema(CANDIDATES, VERDICTS, enum=False))
    sent = fake.calls[0]["response_format"]["json_schema"]["schema"]
    assert sent["properties"]["offender"]["anyOf"][0]["pattern"] == ruling.OFFENDER_PATTERN


# ------------------------------------------------------------------------------- the proxy cache


@pytest.mark.parametrize("word", ["hit", None, "maybe"])
def test_a_reply_not_said_fresh_is_stored_then_refused(
    monkeypatch, env, tmp_path, word: str | None
) -> None:
    ledger = Ledger(tmp_path / "ledger")
    fake = install(monkeypatch, [reply()] * 3, cache=["miss", word, "miss"])
    fake.cache = ["miss", word, "miss"]  # None here means: no header at all
    with pytest.raises(ruling.RulingError, match="r15-run2") as err:
        do_read(ledger)
    assert "fresh" in str(err.value)
    stored = sorted(ledger.entries(), key=lambda e: str(e["cached"]))
    assert len(stored) == 2  # run 1 and the refused run 2, so both are counted as spent
    refused = [e for e in stored if e["cached"] is not False]
    assert len(refused) == 1
    assert refused[0]["cache_header"] == word
    # Reading it back later refuses again: a stored cached reply never becomes a run.
    install(monkeypatch, [reply()] * 3)
    with pytest.raises(ruling.RulingError, match="r15-run2"):
        do_read(ledger)


def test_a_reply_with_no_usage_is_stored_and_priced(monkeypatch, env, tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger")
    fake = install(monkeypatch, [reply()] * 3)
    fake.usage = None
    got = do_read(ledger)
    assert got.agreed is True
    entries = list(ledger.entries())
    assert len(entries) == 3
    for e in entries:
        assert e["usage"] == {"prompt_tokens": None, "completion_tokens": None}
        assert client.entry_cost(e) == pytest.approx(client.PRICES[MODEL]["per_call_fallback"])


def test_a_reply_with_no_usage_and_an_odd_header_is_kept_after_the_refusal(
    monkeypatch, env, tmp_path
) -> None:
    ledger = Ledger(tmp_path / "ledger")
    fake = install(monkeypatch, [reply()] * 3, cache=["odd-value"])
    fake.usage = None
    with pytest.raises(ruling.RulingError, match="r15-run1"):
        do_read(ledger)
    (entry,) = list(ledger.entries())
    assert entry["usage"] == {"prompt_tokens": None, "completion_tokens": None}
    assert entry["cached"] is None and entry["cache_header"] == "odd-value"


def test_a_planted_name_in_a_reason_is_a_failed_run_and_recorded(
    monkeypatch, env, tmp_path
) -> None:
    named = REASON[:-1] + " Verna Talbrook braked late."
    ledger = Ledger(tmp_path / "ledger")
    install(monkeypatch, [reply("7"), reply("7", reason=named), reply("7")])
    got = do_read(ledger)
    assert got.agreed is False and got.lint_hits == 1 and got.parse_failures == 1
    hits = [e["name_hit"] for e in ledger.entries()]
    assert sorted(hits) == [False, False, True]
    # The flag is a bare boolean: the matched text is never written beside it.
    assert all(isinstance(e["name_hit"], bool) for e in ledger.entries())
    # A replay with no names still sees the stored hit.
    again = do_read(ledger, names=[], replay_only=True)
    assert again.as_dict() == got.as_dict()


def test_validate_refuses_duplicate_keys_and_empty_frames() -> None:
    dup = reply("7")[:-1] + ', "verdict": "no_action"}'
    assert ruling.validate(dup, CANDIDATES, LABELS, VERDICTS) is None
    assert ruling.validate(reply("7", frames_used=[]), CANDIDATES, LABELS, VERDICTS) is None


def test_the_core_holds_no_verdict_words() -> None:
    assert not hasattr(ruling, "VERDICTS")
    with pytest.raises(ruling.RulingError):
        ruling.Verdicts((("a", "x"),), naming="b")


def test_a_fake_read_says_so(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    got = do_read(Ledger(tmp_path / "ledger"))
    assert got.as_dict()["source"] == "fake"


def test_replay_only_never_calls_the_client(monkeypatch, env, tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger")
    install(monkeypatch, [reply()] * 3)
    first = do_read(ledger)

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a replay must not call the client")

    monkeypatch.setattr(client, "chat", boom)
    assert do_read(ledger, replay_only=True).as_dict() == first.as_dict()
    with pytest.raises(ruling.RulingError, match="never calls"):
        do_read(Ledger(tmp_path / "empty"), replay_only=True)


def test_the_module_has_no_order_matching_left() -> None:
    assert not hasattr(ruling, "proxy_uncached") and not hasattr(ruling, "last_seq")


# ------------------------------------------------------------- the reply's name check

PATH_SHAPED_REASON = (
    "Rule 9.5/9.5.2: frames 1/2/3 show 7 closing at 5.6m/s, careless/non-intentional."
)


def test_path_shapes_in_a_reason_are_not_a_lint_hit(monkeypatch, env, tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger")
    install(monkeypatch, [reply("7", reason=PATH_SHAPED_REASON)] * 3)
    got = do_read(ledger)
    assert got.lint_hits == 0 and got.parse_failures == 0 and got.agreed is True
    assert [e["name_hit"] for e in ledger.entries()] == [False, False, False]
    assert all("lint_hit" not in e for e in ledger.entries())


@pytest.mark.parametrize(
    "leak",
    [" Verna Talbrook braked late.", " Mail someone@example.org.", " See https://example.invalid."],
)
def test_a_name_email_or_url_in_a_reason_fails_the_run(
    monkeypatch, env, tmp_path, leak: str
) -> None:
    ledger = Ledger(tmp_path / "ledger")
    leaked = PATH_SHAPED_REASON[:-1] + "." + leak
    install(monkeypatch, [reply("7", reason=leaked), reply("7"), reply("7")])
    got = do_read(ledger)
    assert got.lint_hits == 1 and got.parse_failures == 1 and got.agreed is False


def test_the_prompt_keeps_the_full_lint(monkeypatch, env, tmp_path) -> None:
    fake = install(monkeypatch, [reply()] * 3)
    with pytest.raises(LintError):
        ruling.read(
            prompt() + "\nSee and/or the clip.\n",
            IMAGES,
            MODEL,
            Ledger(tmp_path / "ledger"),
            "r15",
            candidates=CANDIDATES,
            frame_labels=LABELS,
            names=NAMES,
            verdicts=VERDICTS,
        )
    assert fake.calls == []


def test_an_old_lint_hit_entry_is_judged_again_clean(monkeypatch, env, tmp_path) -> None:
    """An entry the old code wrote with `lint_hit: true` for path shapes alone reads clean."""
    first = Ledger(tmp_path / "first")
    install(monkeypatch, [reply("7", reason=PATH_SHAPED_REASON)] * 3)
    do_read(first)
    old = Ledger(tmp_path / "old")
    for path in sorted(first.root.glob("*.json")):
        entry = json.loads(path.read_text("utf-8"))
        del entry["name_hit"]
        entry["lint_hit"] = True  # what the full lint wrote for these path shapes
        old.put(path.stem, entry)
    before = {p.name: p.read_bytes() for p in old.root.glob("*.json")}
    got = do_read(old)
    assert got.lint_hits == 0 and got.parse_failures == 0 and got.agreed is True
    assert got.sent_refs == ()
    again = do_read(old, names=[], replay_only=True)
    assert again.as_dict() == got.as_dict()
    # Nothing was rewritten: the ledger never overwrites a recorded entry.
    assert {p.name: p.read_bytes() for p in old.root.glob("*.json")} == before
