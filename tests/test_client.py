"""Tests for faultline.client: fake transport only, never a real network call."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from faultline import client

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["breach", "no_breach", "unclear"]},
        "subject": {"anyOf": [{"type": "string", "pattern": "^[0-9]{1,3}$"}, {"type": "null"}]},
        "offender": {"anyOf": [{"type": "string", "enum": ["7", "12", "33"]}, {"type": "null"}]},
        "reason": {"type": "string"},
        "frame_index": {"type": "integer", "minimum": 0, "maximum": 21},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "verdict",
        "subject",
        "offender",
        "reason",
        "frame_index",
        "confidence",
        "evidence",
    ],
    "additionalProperties": False,
}

MESSAGES = [{"role": "user", "content": "Which subject broke the rule?"}]
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"


class Recorder:
    """A fake transport: records every request and answers through an httpx.MockTransport."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status
        self.body = body or {
            "choices": [
                {"message": {"content": '{"verdict": "breach"}'}, "finish_reason": "length"}
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }
        self._http = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self.status, json=self.body)

    def __call__(self, url: str, headers: dict[str, str], payload: dict[str, Any]):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
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


def write_env(env_file, base: str) -> None:
    env_file.write_text(f"MODEL_API_KEY=test-key-not-real\nMODEL_API_BASE={base}\n", "utf-8")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(client, "CLIENT", rec)
    return rec


def test_settings_read_from_env_file(env) -> None:
    key, base = client.settings()
    assert key == "test-key-not-real"
    assert base == "http://127.0.0.1:9/v1"


def test_chat_returns_text_and_usage(env, fake: Recorder) -> None:
    reply = client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert reply.text == '{"verdict": "breach"}'
    assert reply.usage == {"prompt_tokens": 120, "completion_tokens": 30}
    assert reply.finish_reason == "length"
    assert len(fake.calls) == 1
    assert fake.calls[0]["url"] == "http://127.0.0.1:9/v1/chat/completions"
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer test-key-not-real"


@pytest.mark.parametrize(
    "base",
    ["https://api.meta.ai/v1", "http://127.0.0.2:8765/v1", "http://localhost.evil.test/v1"],
)
def test_non_loopback_base_refused(env, fake: Recorder, base: str) -> None:
    write_env(env, base)
    with pytest.raises(client.ClientError, match="metering proxy"):
        client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert fake.calls == []


def test_localhost_base_allowed(env, fake: Recorder) -> None:
    write_env(env, "http://localhost:8765/v1/")
    client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert fake.calls[0]["url"] == "http://localhost:8765/v1/chat/completions"


def test_error_messages_never_carry_the_key(env) -> None:
    write_env(env, "https://api.meta.ai/v1")
    with pytest.raises(client.ClientError) as info:
        client.settings()
    assert "test-key-not-real" not in str(info.value)
    assert str(env) not in str(info.value)


def test_env_file_wins_over_shell(env, fake: Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "shell-key-must-not-travel")
    monkeypatch.setenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    assert client.settings() == ("test-key-not-real", "http://127.0.0.1:9/v1")
    client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer test-key-not-real"


def test_env_file_set_but_missing_refused(env, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "shell-key-must-not-travel")
    monkeypatch.setenv("MODEL_API_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("STEWARD_ENV_FILE", str(tmp_path / "absent.env"))
    with pytest.raises(client.ClientError, match="no readable file"):
        client.settings()


def test_shell_environment_used_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STEWARD_ENV_FILE", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "shell-test-key")
    monkeypatch.setenv("MODEL_API_BASE", "http://127.0.0.1:9/v1")
    assert client.settings() == ("shell-test-key", "http://127.0.0.1:9/v1")


def test_post_ignores_outside_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen.update(kwargs)
        return httpx.Response(200, json={})

    monkeypatch.setattr(client.httpx, "post", fake_post)
    client._post("http://127.0.0.1:9/v1/chat/completions", {}, {})
    assert seen["trust_env"] is False


def test_budget_429_stops_without_retry(env, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder(
        status=429,
        body={"error": {"type": "tourney_budget", "message": "token budget spent: $90.00"}},
    )
    monkeypatch.setattr(client, "CLIENT", rec)
    with pytest.raises(SystemExit) as info:
        client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert str(info.value) == "token budget spent: $90.00"
    assert len(rec.calls) == 1


def test_other_http_failure_raises_client_error(env, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder(status=500, body={"error": "boom"})
    monkeypatch.setattr(client, "CLIENT", rec)
    with pytest.raises(client.ClientError, match="HTTP 500"):
        client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert len(rec.calls) == 1


def test_cap_refuses_before_any_request(
    env, fake: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_CAP_USD", "1.00")
    spent = [
        {
            "model": "muse-spark-1.3",
            "usage": {"prompt_tokens": 400_000, "completion_tokens": 120_000},
        }
    ]  # $0.50 + $0.51 = $1.01 already, before the 8000-token reply estimate
    with pytest.raises(client.ClientError, match="cost cap"):
        client.chat(MESSAGES, "muse-spark-1.3", spent_entries=spent)
    assert fake.calls == []


def test_cap_default_is_five_dollars(env, fake: Recorder) -> None:
    under = [
        {"model": "muse-wonder-1.0", "usage": {"prompt_tokens": 0, "completion_tokens": 200_000}}
    ]
    client.chat(MESSAGES, "muse-spark-1.3", spent_entries=under)  # $4.00 spent, passes
    over = under + [
        {"model": "muse-wonder-1.0", "usage": {"prompt_tokens": 0, "completion_tokens": 49_000}}
    ]  # $4.98 spent: an 8000-token estimate on top passes $5.00
    with pytest.raises(client.ClientError, match="cost cap"):
        client.chat(MESSAGES, "muse-spark-1.3", spent_entries=over)
    assert len(fake.calls) == 1


def test_unknown_model_refused(env, fake: Recorder) -> None:
    with pytest.raises(client.ClientError, match="no price row"):
        client.chat(MESSAGES, "some-new-model", spent_entries=[])
    assert fake.calls == []


def test_unknown_model_in_spent_entries_refused(env, fake: Recorder) -> None:
    spent = [{"model": "mystery", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}]
    with pytest.raises(client.ClientError, match="no price row"):
        client.chat(MESSAGES, "muse-spark-1.3", spent_entries=spent)
    assert fake.calls == []


def test_entry_cost_prices() -> None:
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert client.entry_cost({"model": "muse-spark-1.3", "usage": usage}) == pytest.approx(5.5)
    assert client.entry_cost({"model": "muse-spark-1.3", "usage": {}}) == pytest.approx(0.05)
    sam = {"model": "sam-3.1", "usage": {"images_processed": 4, "video_frames_processed": 10}}
    assert client.entry_cost(sam) == pytest.approx(4 * 0.0025 + 50 * 0.0002)


def test_estimate_grows_with_images() -> None:
    plain = client.estimate_cost("muse-spark-1.3", MESSAGES, 0, 20_000)
    with_images = client.estimate_cost("muse-spark-1.3", MESSAGES, 5, 20_000)
    assert with_images > plain


def test_request_body_carries_data_uri_and_response_format(env, fake: Recorder) -> None:
    client.chat(
        MESSAGES, "muse-spark-1.3", images=[JPEG], schema=SCHEMA, max_tokens=4000, spent_entries=[]
    )
    payload = fake.calls[0]["payload"]
    assert payload["model"] == "muse-spark-1.3"
    assert payload["max_tokens"] == 4000
    parts = payload["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "Which subject broke the rule?"}
    uri = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode("ascii")
    assert parts[1] == {"type": "image_url", "image_url": {"url": uri}}
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": client.SCHEMA_NAME, "strict": True, "schema": SCHEMA},
    }
    assert MESSAGES[0]["content"] == "Which subject broke the rule?"  # caller's list untouched


def test_no_schema_sends_no_response_format(env, fake: Recorder) -> None:
    client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert "response_format" not in fake.calls[0]["payload"]


def test_image_path_read_as_bytes(env, fake: Recorder, tmp_path) -> None:
    path = tmp_path / "frame.jpg"
    path.write_bytes(JPEG)
    client.chat(MESSAGES, "muse-spark-1.3", images=[path], spent_entries=[])
    url = fake.calls[0]["payload"]["messages"][-1]["content"][1]["image_url"]["url"]
    assert url.endswith(base64.b64encode(JPEG).decode("ascii"))


def _valid(value: Any, schema: dict[str, Any]) -> bool:
    """A small schema check covering what SCHEMA uses (no jsonschema dependency)."""
    if "enum" in schema:
        return value in schema["enum"]
    if "anyOf" in schema:
        return any(_valid(value, s) for s in schema["anyOf"])
    kind = schema["type"]
    if kind == "null":
        return value is None
    if kind == "object":
        props = schema["properties"]
        return (
            isinstance(value, dict)
            and set(value) == set(schema["required"]) == set(props)
            and all(_valid(value[k], props[k]) for k in props)
        )
    if kind == "array":
        return isinstance(value, list) and all(_valid(v, schema["items"]) for v in value)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and schema["minimum"] <= value <= schema["maximum"]
    if kind == "number":
        return isinstance(value, int | float) and schema["minimum"] <= value <= schema["maximum"]
    return False


def test_fake_model_returns_schema_valid_json_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("MODEL_API_KEY", "MODEL_API_BASE", "STEWARD_ENV_FILE"):
        monkeypatch.delenv(name, raising=False)

    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the fake model seam must not send a request")

    monkeypatch.setattr(client, "CLIENT", no_network)
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    first = client.chat(MESSAGES, "muse-spark-1.3", images=[JPEG], schema=SCHEMA, spent_entries=[])
    second = client.chat(MESSAGES, "muse-spark-1.3", images=[JPEG], schema=SCHEMA, spent_entries=[])
    assert first == second
    value = json.loads(first.text)
    assert _valid(value, SCHEMA)
    assert value["subject"] is None
    assert len(value["reason"]) >= 40
    assert first.usage == {"prompt_tokens": 0, "completion_tokens": 0}
    assert first.finish_reason == "stop"


def test_fake_model_varies_with_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "CLIENT", None)
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    replies = []
    for nonce in range(40):
        msgs = [{"role": "user", "content": f"Which subject broke the rule? nonce {nonce}"}]
        reply = client.chat(msgs, "muse-spark-1.3", schema=SCHEMA, spent_entries=[])
        again = client.chat(msgs, "muse-spark-1.3", schema=SCHEMA, spent_entries=[])
        assert reply == again
        value = json.loads(reply.text)
        assert _valid(value, SCHEMA)
        replies.append(reply.text)
    assert len(set(replies)) >= 2
    offenders = {json.loads(t)["offender"] for t in replies}
    verdicts = {json.loads(t)["verdict"] for t in replies}
    assert None in offenders and len(offenders) >= 3  # enum values and null both reached
    assert len(verdicts) >= 2


def test_request_params_match_the_body(env, fake: Recorder) -> None:
    params = client.request_params("muse-spark-1.3", SCHEMA, 4000)
    assert params["source"] == "model"
    client.chat(
        MESSAGES, "muse-spark-1.3", images=[JPEG], schema=SCHEMA, max_tokens=4000, spent_entries=[]
    )
    payload = dict(fake.calls[0]["payload"])
    del payload["messages"]
    assert payload == {k: v for k, v in params.items() if k != "source"}
    assert client.request_params("muse-spark-1.3") == {
        "model": "muse-spark-1.3",
        "temperature": 0,
        "max_tokens": client.DEFAULT_MAX_TOKENS,
        "source": "model",
    }


def test_request_params_mark_fake_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    real = client.request_params("muse-spark-1.3", SCHEMA)
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    fake_params = client.request_params("muse-spark-1.3", SCHEMA)
    assert fake_params["source"] == "fake"
    assert fake_params != real


def test_spent_entries_is_required(env, fake: Recorder) -> None:
    with pytest.raises(TypeError):
        client.chat(MESSAGES, "muse-spark-1.3")  # type: ignore[call-arg]
    assert fake.calls == []


def test_reply_without_usage_keeps_none(env, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder(body={"choices": [{"message": {"content": "ok"}}], "usage": None})
    monkeypatch.setattr(client, "CLIENT", rec)
    reply = client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[])
    assert reply.usage == {"prompt_tokens": None, "completion_tokens": None}
    assert reply.finish_reason is None
    entry = {"model": "muse-spark-1.3", "usage": reply.usage}
    assert client.entry_cost(entry) == pytest.approx(0.05)


def test_entry_cost_charges_fallback_when_one_count_is_none() -> None:
    half = {"model": "muse-spark-1.3", "usage": {"prompt_tokens": 10, "completion_tokens": None}}
    assert client.entry_cost(half) == pytest.approx(0.05)
    assert client.entry_cost({"model": "muse-spark-1.3", "usage": None}) == pytest.approx(0.05)


@pytest.mark.parametrize("bad", ["12", 1.5, True, -1, [3]])
def test_entry_cost_refuses_non_int_usage(bad: Any) -> None:
    entry = {"model": "muse-spark-1.3", "usage": {"prompt_tokens": bad, "completion_tokens": 1}}
    with pytest.raises(client.ClientError, match="prompt_tokens"):
        client.entry_cost(entry)


def test_fake_model_without_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAULTLINE_FAKE_MODEL", "1")
    assert client.chat(MESSAGES, "muse-spark-1.3", spent_entries=[]).text == client.FAKE_TEXT


def test_core_module_stays_domain_neutral() -> None:
    source = open(client.__file__, encoding="utf-8").read().lower()
    assert "faultline.adapters" not in source
    for word in (" car ", " cars ", " lap ", " laps ", "incident"):
        assert word not in source
