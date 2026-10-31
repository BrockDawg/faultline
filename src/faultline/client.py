"""Model API client: one OpenAI-compatible chat call through the local metering proxy.

Contract:

- `settings()` reads `MODEL_API_KEY` and `MODEL_API_BASE` from the file `STEWARD_ENV_FILE`
  names; when that is set, the shell environment is not used. Without it, the environment is
  read. The key and the file are never printed, logged or put in an error message.
- `chat(messages, model, images=(), schema=None, max_tokens=8000, *, spent_entries)` posts one
  `/chat/completions` request and returns a `Reply` (the reply text, its `usage` holding
  `prompt_tokens` and `completion_tokens` with None for an absent count, and `finish_reason`).
  `spent_entries` is required, so the cap cannot be skipped by leaving it out.
  `Reply.cached` is the metering proxy's own word on whether it served the reply from its
  cache: the response header `X-Tourney-Cache` (`hit` is True, `miss` is False; absent or any
  other value is None), and `Reply.cache_header` is the header as sent (None when absent).
  An odd header never raises: the call was paid, so the reply always comes back for the
  caller to store before it refuses. Images are JPEG
  bytes (or paths to JPEG files) sent as base64 data URIs in the last message. A `schema` is
  sent as strict structured output: `response_format = {"type": "json_schema", "json_schema":
  {"name": ..., "strict": True, "schema": schema}}`, the shape that worked with images in
  the private working repo's second batch.
- `request_params(model, schema=None, max_tokens=8000)` is every field `chat` sends besides
  messages and images, plus `source` ("fake" or "model"). The caller passes it as the ledger
  key's params; `chat` builds its body from it, so the key always matches what was sent.

It refuses (`ClientError`), before any request is sent:

- a base whose host is not `127.0.0.1` or `localhost`, so every paid call passes the metering
  proxy;
- a model with no row in `PRICES` (an unknown model is never priced at zero);
- a call whose estimated cost, added to the priced cost of every entry in `spent_entries`
  (dicts holding `model` and `usage`, as the ledger stores them), would pass
  `FAULTLINE_CAP_USD` (default 5.00). The cap is per ledger folder: `spent_entries` is one
  ledger's entries, so spend recorded in another folder is not counted against it. The
  estimate counts prompt tokens from the text length and the image count, and `max_tokens`
  as completion tokens.

A 429 from the proxy (its budget is spent) stops the run: `SystemExit` with the proxy's message.
It is never retried. Any other HTTP failure or an unexpected reply shape raises `ClientError`.

Test-only seam: with `FAULTLINE_FAKE_MODEL=1`, `chat` sends nothing and needs no key. It returns
a reply with zero usage and finish reason "stop". With a schema, the reply is JSON built from
the schema (`fake_value`), its enum choices picked from a sha256 of all the prompt text: the
same prompt always gives the same reply, and a different prompt can give a different one.
Never set it for a real run.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

__all__ = [
    "CACHE_HEADER",
    "CLIENT",
    "ClientError",
    "PRICES",
    "Reply",
    "chat",
    "entry_cost",
    "estimate_cost",
    "fake_value",
    "request_params",
    "settings",
]

DEFAULT_CAP_USD = 5.00
DEFAULT_MAX_TOKENS = 8000
SCHEMA_NAME = "faultline_reply"
CHARS_PER_TOKEN = 3  # deliberately low (real text runs nearer 4), so the estimate over-counts
TOKENS_PER_IMAGE = 2000  # a generous per-image allowance, the safe side of the cap
TIMEOUT_S = 900.0
FAKE_REASON = "Fixed test reply from the fake model seam; no model was called."
FAKE_TEXT = "fake model reply"
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
CACHE_HEADER = "X-Tourney-Cache"
_CACHE_VALUES = {"hit": True, "miss": False}

# Prices copied as data from the private working repo's price table (verified there 2026-10-25
# from the Meta Model API pricing page, Standard mode, and the Baseten library page; copied
# 2026-10-29).
# "in" and "out" are USD per 1M tokens; "per_call_fallback" is charged for a reply with no usage.
# sam-3.1 bills per unit: usage.images_processed at per_image and usage.video_frames_processed
# at per_frame with a min_frames floor per video call.
PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-5-5": {"in": 0.1, "out": 0.5, "per_call_fallback": 0.015},
    "claude-haiku-5-5@long": {"in": 0.5, "out": 2.5, "per_call_fallback": 0.015},
    "meta-models/muse-spark-open": {"in": 1.25, "out": 4.25, "per_call_fallback": 0.05},
    "meta-models/muse-spark-open-1026": {"in": 1.25, "out": 4.25, "per_call_fallback": 0.05},
    "muse-spark-1.3": {"in": 1.25, "out": 4.25, "per_call_fallback": 0.05},
    "muse-spark-1.2": {"in": 1.25, "out": 4.25, "per_call_fallback": 0.05},
    "muse-spark-1.1": {"in": 1.25, "out": 4.25, "per_call_fallback": 0.05},
    "muse-wonder-1.0": {"in": 4.0, "out": 20.0, "per_call_fallback": 0.1},
    "muse-voice-transcribe-1.0": {"in": 0.0, "out": 0.0, "per_call_fallback": 0.05},
    "sam-3.1": {
        "in": 0.0,
        "out": 0.0,
        "per_call_fallback": 0.0025,
        "per_image": 0.0025,
        "per_frame": 0.0002,
        "min_frames": 50,
    },
}


class ClientError(RuntimeError):
    """A model call was refused or failed; the message names the reason, never the key."""


@dataclass(frozen=True)
class Reply:
    """One model reply: its text, the usage the API reported (None for an absent count), and
    the finish reason (None when the API gave none), and `cached`, the proxy's cache header
    (True for a reply served from its cache, False for a fresh one, None when absent or odd)
    with `cache_header`, the header's raw value (None when absent)."""

    text: str
    usage: dict[str, int | None] = field(default_factory=dict)
    finish_reason: str | None = None
    cached: bool | None = None
    cache_header: str | None = None


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> httpx.Response:
    # trust_env=False: no HTTP(S)_PROXY from the shell ever sees the bearer token.
    return httpx.post(url, headers=headers, json=payload, timeout=TIMEOUT_S, trust_env=False)


# The seam: tests replace it with a callable (url, headers, payload) -> httpx.Response.
CLIENT: Callable[[str, dict[str, str], dict[str, Any]], httpx.Response] = _post


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[name] = value
    return out


def _check_loopback(base: str) -> None:
    host = (urlsplit(base).hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise ClientError(
            f"the model API base must be the local metering proxy (127.0.0.1 or localhost), "
            f"not host {host or '(none)'!r}"
        )


def settings() -> tuple[str, str]:
    """Return (api_key, api_base).

    When `STEWARD_ENV_FILE` is set, only that file is read: a key in the shell environment never
    goes to the proxy. Without it, the shell's `MODEL_API_KEY` and `MODEL_API_BASE` are used.
    """
    env_file = os.environ.get("STEWARD_ENV_FILE", "")
    if env_file:
        if not Path(env_file).is_file():
            raise ClientError("STEWARD_ENV_FILE is set but names no readable file")
        values = _read_env_file(Path(env_file))
        key = values.get("MODEL_API_KEY", "")
        base = values.get("MODEL_API_BASE", "")
        where = "the file STEWARD_ENV_FILE names"
    else:
        key = os.environ.get("MODEL_API_KEY", "")
        base = os.environ.get("MODEL_API_BASE", "")
        where = "the environment (STEWARD_ENV_FILE is not set)"
    if not key:
        raise ClientError(f"MODEL_API_KEY is missing from {where}")
    if not base:
        raise ClientError(f"MODEL_API_BASE is missing from {where}")
    base = base.rstrip("/")
    _check_loopback(base)
    return key, base


def _price(model: str) -> dict[str, float]:
    row = PRICES.get(model)
    if row is None:
        raise ClientError(f"model {model!r} has no price row; refusing to call or price it")
    return row


def _count(value: Any, what: str) -> int | None:
    """A usage count: None stays None, a non-negative int passes, anything else is refused."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClientError(f"usage {what} is not a non-negative integer: {value!r}")
    return value


def entry_cost(entry: Mapping[str, Any]) -> float:
    """USD cost of one ledger entry (a dict with `model` and `usage`), priced from `PRICES`.

    A token model whose `prompt_tokens` or `completion_tokens` is absent or None is charged its
    `per_call_fallback`, never $0.
    """
    model = str(entry.get("model", ""))
    row = _price(model)
    usage = entry.get("usage")
    if usage is None:
        usage = {}
    if not isinstance(usage, Mapping):
        raise ClientError(f"ledger entry for {model!r} has a usage that is not an object")
    if "per_image" in row:
        images = _count(usage.get("images_processed"), "images_processed") or 0
        frames = _count(usage.get("video_frames_processed"), "video_frames_processed") or 0
        if frames:
            frames = max(frames, int(row["min_frames"]))
        if not images and not frames:
            return row["per_call_fallback"]
        return images * row["per_image"] + frames * row["per_frame"]
    prompt = _count(usage.get("prompt_tokens"), "prompt_tokens")
    completion = _count(usage.get("completion_tokens"), "completion_tokens")
    if prompt is None or completion is None:
        return row["per_call_fallback"]
    return (prompt * row["in"] + completion * row["out"]) / 1_000_000


def _texts(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "text":
                    out.append(str(part.get("text", "")))
    return out


def _text_chars(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(t) for t in _texts(messages))


def estimate_cost(
    model: str,
    messages: Sequence[Mapping[str, Any]],
    n_images: int,
    max_tokens: int,
    schema: Mapping[str, Any] | None = None,
) -> float:
    """Upper-side USD estimate of one call: prompt from text and images, `max_tokens` as output."""
    row = _price(model)
    chars = _text_chars(messages)
    if schema is not None:
        chars += len(json.dumps(schema))
    prompt_tokens = math.ceil(chars / CHARS_PER_TOKEN) + n_images * TOKENS_PER_IMAGE
    if "per_image" in row:
        return max(n_images * row["per_image"], row["per_call_fallback"])
    tokens_cost = (prompt_tokens * row["in"] + max_tokens * row["out"]) / 1_000_000
    return max(tokens_cost, row["per_call_fallback"])


def _cap_usd() -> float:
    raw = os.environ.get("FAULTLINE_CAP_USD", "")
    if not raw:
        return DEFAULT_CAP_USD
    try:
        cap = float(raw)
    except ValueError as exc:
        raise ClientError(f"FAULTLINE_CAP_USD is not a number: {raw!r}") from exc
    if not math.isfinite(cap) or cap < 0:
        raise ClientError(f"FAULTLINE_CAP_USD must be a finite number of dollars, not {raw!r}")
    return cap


def _check_cap(estimate: float, spent_entries: Iterable[Mapping[str, Any]]) -> None:
    spent = sum(entry_cost(e) for e in spent_entries)
    cap = _cap_usd()
    if spent + estimate > cap:
        raise ClientError(
            f"cost cap: ${spent:.4f} already spent plus this call's estimate ${estimate:.4f} "
            f"would pass FAULTLINE_CAP_USD ${cap:.2f}; no request sent"
        )


def _image_bytes(image: bytes | Path | str) -> bytes:
    if isinstance(image, bytes):
        return image
    return Path(image).read_bytes()


def _with_images(
    messages: Sequence[Mapping[str, Any]], images: Sequence[bytes | Path | str]
) -> list[dict[str, Any]]:
    out = [dict(m) for m in messages]
    if not images:
        return out
    last = out[-1]
    content = last.get("content", "")
    parts: list[dict[str, Any]] = (
        [dict(p) for p in content]
        if isinstance(content, list)
        else [{"type": "text", "text": str(content)}]
    )
    for image in images:
        uri = "data:image/jpeg;base64," + base64.b64encode(_image_bytes(image)).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": uri}})
    last["content"] = parts
    return out


def _stop_on_budget(resp: httpx.Response) -> None:
    if resp.status_code != 429:
        return
    message = ""
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            message = str(err.get("message") or "")
        elif isinstance(err, str):
            message = err
    except ValueError:
        message = resp.text[:300]
    raise SystemExit(message or "the metering proxy answered 429: this token's budget is spent")


def _cached(resp: httpx.Response) -> tuple[bool | None, str | None]:
    """(cached, raw header): never raises, since the call has already been paid for."""
    raw = resp.headers.get(CACHE_HEADER)
    if raw is None:
        return None, None
    return _CACHE_VALUES.get(raw.strip().lower()), raw[:80]


def _pick(seed: str, path: str, n: int) -> int:
    digest = hashlib.sha256(f"{seed}\n{path}".encode()).hexdigest()
    return int(digest, 16) % n


def fake_value(schema: Mapping[str, Any], seed: str = "", path: str = "$") -> Any:
    """A value valid under `schema` (test-only), chosen deterministically from `seed`.

    An `enum` takes index sha256(seed, path) mod its length. An anyOf holding an enum and a
    null picks among every enum value and null the same way. Any other anyOf with a null gives
    null; the rest are fixed (see the module docstring).
    """
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        values = list(schema["enum"])
        return values[_pick(seed, path, len(values))]
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        has_null = any(o.get("type") == "null" for o in options)
        enums = [v for o in options if "enum" in o for v in o["enum"]]
        if has_null and enums:
            choices = [*enums, None]
            return choices[_pick(seed, path, len(choices))]
        if has_null:
            return None
        return fake_value(options[0], seed, path)
    kind = schema.get("type")
    if isinstance(kind, list):
        if "null" in kind:
            return None
        kind = kind[0]
    if kind == "null":
        return None
    if kind == "object":
        props = schema.get("properties") or {}
        return {name: fake_value(sub, seed, f"{path}.{name}") for name, sub in props.items()}
    if kind == "array":
        count = int(schema.get("minItems") or 0)
        items = schema.get("items") or {}
        return [fake_value(items, seed, f"{path}[{i}]") for i in range(count)]
    if kind == "string":
        if "pattern" in schema:
            raise ClientError("the fake model cannot fill a string with a pattern and no null")
        return FAKE_REASON
    if kind in ("integer", "number"):
        low = schema.get("minimum", 0)
        return int(low) if kind == "integer" else float(low)
    if kind == "boolean":
        return False
    raise ClientError(f"the fake model cannot fill a schema of type {kind!r}")


def _fake_mode() -> bool:
    return os.environ.get("FAULTLINE_FAKE_MODEL") == "1"


def _fake_reply(messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any] | None) -> Reply:
    if schema is None:
        text = FAKE_TEXT
    else:
        seed = hashlib.sha256(json.dumps(_texts(messages)).encode("utf-8")).hexdigest()
        text = json.dumps(fake_value(schema, seed), sort_keys=True)
    usage: dict[str, int | None] = {"prompt_tokens": 0, "completion_tokens": 0}
    return Reply(text=text, usage=usage, finish_reason="stop")


def request_params(
    model: str, schema: Mapping[str, Any] | None = None, max_tokens: int = DEFAULT_MAX_TOKENS
) -> dict[str, Any]:
    """Every field `chat` sends besides messages and images, plus `source`.

    `source` is "fake" under `FAULTLINE_FAKE_MODEL=1`, else "model"; it is never sent. `chat`
    builds its request body from this same function, so a caller that passes
    `request_params(...)` as the ledger key's params always keys exactly what was sent, and a
    fake reply never shares a key with a real one.
    """
    params: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "source": "fake" if _fake_mode() else "model",
    }
    if schema is not None:
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": dict(schema)},
        }
    return params


def chat(
    messages: Sequence[Mapping[str, Any]],
    model: str,
    images: Sequence[bytes | Path | str] = (),
    schema: Mapping[str, Any] | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    *,
    spent_entries: Iterable[Mapping[str, Any]],
) -> Reply:
    """One chat completion through the metering proxy; see the module docstring for refusals.

    `spent_entries` is required: pass the ledger's `entries()` (an empty ledger passes `[]`).
    """
    if not messages:
        raise ClientError("chat needs at least one message")
    if _fake_mode():
        return _fake_reply(messages, schema)
    estimate = estimate_cost(model, messages, len(images), max_tokens, schema)
    _check_cap(estimate, spent_entries)
    key, base = settings()
    params = request_params(model, schema, max_tokens)
    payload = {k: v for k, v in params.items() if k != "source"}
    payload["messages"] = _with_images(messages, images)
    resp = CLIENT(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, payload)
    _stop_on_budget(resp)
    if resp.status_code >= 400:
        raise ClientError(f"HTTP {resp.status_code} from the model API: {resp.text[:200]}")
    try:
        body = resp.json()
        choice = body["choices"][0]
        text = choice["message"]["content"]
        finish = choice.get("finish_reason")
        usage = body.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise TypeError("usage is not an object")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ClientError(f"unexpected reply shape from the model API ({exc!r})") from exc
    cached, cache_header = _cached(resp)
    return Reply(
        text=str(text or ""),
        usage={
            "prompt_tokens": _count(usage.get("prompt_tokens"), "prompt_tokens"),
            "completion_tokens": _count(usage.get("completion_tokens"), "completion_tokens"),
        },
        finish_reason=None if finish is None else str(finish),
        cached=cached,
        cache_header=cache_header,
    )
