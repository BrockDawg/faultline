"""Model API client: settings are read, never printed; every paid call is ledgered; a budget 429
stops the run.

MODEL_API_KEY and MODEL_API_BASE come from the environment first, then from the file
STEWARD_ENV_FILE names (the same way the reference client does). The file's contents are never
echoed, copied or written anywhere.

Meta's open-weight models (ids under `meta-models/`, Muse Spark Open here) are served by Baseten:
when BASETEN_API_KEY is set, every call to one of them goes to BASETEN_API_BASE (default
https://inference.baseten.co/v1) with that key, and everything else (SAM 3.1, Muse Wonder) goes
to MODEL_API_BASE. Without BASETEN_API_KEY every call goes to MODEL_API_BASE, which is then a
router or proxy that knows the model names.

The spend cap is FAULTLINE_CAP_USD (default LOCAL_CAP_USD). Before each paid call the worst case
is reserved in the ledger under an exclusive `<ledger>.lock`, so two processes sharing a ledger
cannot both pass the check; the call's real row then settles the reserve, and a failed call
releases it. A refused call writes nothing.
"""

from __future__ import annotations

import base64
import contextlib
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx

DEFAULT_BASE = "https://api.meta.ai/v1"
BASETEN_BASE = "https://inference.baseten.co/v1"
OPEN_WEIGHT_PREFIX = "meta-models/"  # Meta's open-weight models, as Baseten names them
# a cache's own word on a reply: absent means a miss, so the spend is counted
CACHE_HEADER = "x-faultline-cache"
# our own stop (the proxy's cap is $5.00 on this token), so the last call never 429s mid-ruling;
# FAULTLINE_CAP_USD overrides it
LOCAL_CAP_USD = 4.90
LOCK_WAIT_S = 60.0  # how long a call waits on another process's check-then-reserve
# the build's start: the stop counts only ledger rows from here (earlier runs paid on other keys)
WAVE_START_TS = 1793346000.0
SAM_FRAME_USD, SAM_IMAGE_USD, SAM_MIN_FRAMES = 0.0002, 0.0025, 50
TOKEN_USD = {  # USD per token, in / out (the per-token prices the estimate uses, Standard mode)
    "muse-spark-1.3": (1.25e-6, 4.25e-6),
    "meta-models/muse-spark-open-1026": (1.25e-6, 4.25e-6),
    "muse-wonder-1.0": (4.0e-6, 20.0e-6),
}

LEDGER = Path(
    os.environ.get(
        "FAULTLINE_LEDGER", str(Path(__file__).resolve().parents[4] / "record" / "ledger.jsonl")
    )
)


class BudgetSpent(SystemExit):
    """The token's budget is spent (the metering proxy's HTTP 429 budget reply) or our local cap is
    reached; never retried.
    """


class ApiError(Exception):
    """A non-budget failure; the caller falls back to 'unable to rule' or a recorded reply."""


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


def settings() -> tuple[str, str]:
    key = os.environ.get("MODEL_API_KEY", "")
    base = os.environ.get("MODEL_API_BASE", "")
    env_file = os.environ.get("STEWARD_ENV_FILE", "")
    if (not key or not base) and env_file and Path(env_file).is_file():
        values = _read_env_file(Path(env_file))
        key = key or values.get("MODEL_API_KEY", "")
        base = base or values.get("MODEL_API_BASE", "")
    if not key:
        raise ApiError("MODEL_API_KEY is not set and STEWARD_ENV_FILE names no file that holds it")
    return key, (base or DEFAULT_BASE).rstrip("/")


def route(model: str) -> tuple[str, str]:
    """(key, base) for one model: an open-weight model goes to Baseten when a Baseten key is set."""
    if model.startswith(OPEN_WEIGHT_PREFIX):
        key = os.environ.get("BASETEN_API_KEY", "")
        base = os.environ.get("BASETEN_API_BASE", "")
        env_file = os.environ.get("STEWARD_ENV_FILE", "")
        if (not key or not base) and env_file and Path(env_file).is_file():
            values = _read_env_file(Path(env_file))
            key = key or values.get("BASETEN_API_KEY", "")
            base = base or values.get("BASETEN_API_BASE", "")
        if key:
            return key, (base or BASETEN_BASE).rstrip("/")
    return settings()


def cap_usd() -> float:
    """FAULTLINE_CAP_USD in dollars, or LOCAL_CAP_USD when it is unset."""
    raw = os.environ.get("FAULTLINE_CAP_USD", "").strip()
    if not raw:
        return LOCAL_CAP_USD
    try:
        cap = float(raw)
    except ValueError as exc:
        raise ApiError(f"FAULTLINE_CAP_USD is not a number: {raw!r}") from exc
    if not math.isfinite(cap) or cap < 0:
        raise ApiError(f"FAULTLINE_CAP_USD must be a finite number of dollars, not {raw!r}")
    return cap


def spent(since: float = 0.0) -> float:
    """Dollars in the ledger from `since`: every paid row, plus each reserve not yet settled or
    released (a settled reserve counts once, as its real row).
    """
    if not LEDGER.exists():
        return 0.0
    rows: list[dict] = []
    closed: set[str] = set()
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        rows.append(row)
        if row.get("settles"):
            closed.add(str(row["settles"]))
    total = 0.0
    for row in rows:
        if row.get("kind") == "reserve" and str(row.get("id")) in closed:
            continue
        try:
            if float(row.get("ts") or 0.0) >= since:
                total += float(row.get("est_usd") or 0.0)
        except (ValueError, TypeError):
            pass
    return total


def _write_row(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _lock_failed(lock_path: Path, deadline: float, exc: OSError) -> None:
    if time.monotonic() > deadline:
        raise ApiError(f"the spend ledger stayed locked ({lock_path.name})") from exc
    time.sleep(0.01)


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """Hold the exclusive `<ledger>.lock` (msvcrt on Windows, flock elsewhere; stdlib only)."""
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    lock_path = LEDGER.with_name(LEDGER.name + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_S
    with open(lock_path, "a+b") as fh:
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    _lock_failed(lock_path, deadline, exc)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    _lock_failed(lock_path, deadline, exc)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _ledger(row: dict) -> None:
    with _locked():
        _write_row(row)


def _reserve(worst: float, tag: str) -> str:
    """Check the cap and reserve `worst` in one locked step; returns the reserve's id. A refusal
    writes nothing and raises BudgetSpent.
    """
    cap = cap_usd()
    with _locked():
        if spent(WAVE_START_TS) + worst > cap:
            raise BudgetSpent(
                f"faultline's local spend cap (${cap:.2f}) would be passed; no new "
                "model call is made"
            )
        rid = uuid.uuid4().hex
        _write_row(
            {
                "ts": time.time(),
                "kind": "reserve",
                "id": rid,
                "tag": tag,
                "est_usd": round(worst, 6),
            }
        )
    return rid


def _release(rid: str) -> None:
    """Close the reserve of a call that failed: nothing was paid, so it stops counting."""
    _ledger({"ts": time.time(), "kind": "release", "settles": rid, "est_usd": 0.0})


def _post(path: str, payload: dict, timeout: float = 600.0) -> httpx.Response:
    key, base = route(str(payload.get("model") or ""))
    return httpx.post(
        f"{base}{path}", headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=timeout
    )


POST = _post  # the seam for tests


def _stop_on_budget(resp: httpx.Response) -> None:
    if resp.status_code == 429 and "budget" in resp.text:
        try:
            err = resp.json().get("error") or {}
        except ValueError:
            err = {}
        raise BudgetSpent(
            err.get("message")
            if isinstance(err, dict) and err.get("message")
            else "this token's budget is spent"
        )


def chat(
    messages: list[dict],
    *,
    model: str,
    max_tokens: int = 2000,
    temperature: float = 0.0,
    images: list[bytes] | tuple[bytes, ...] = (),
    worst_usd: float | None = None,
    tag: str = "",
    extra: dict | None = None,
) -> dict:
    """One chat completion. Returns {text, usage, est_usd, cache, finish}. Images ride as JPEG data
    URIs.
    """
    rate_in, rate_out = TOKEN_USD.get(model, (1.25e-6, 4.25e-6))
    worst = worst_usd if worst_usd is not None else 6000 * rate_in + max_tokens * rate_out
    rid = _reserve(worst, tag)
    try:
        return _chat_call(messages, model, max_tokens, temperature, images, tag, extra, rid)
    except BaseException:
        _release(rid)
        raise


def _chat_call(
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    images: list[bytes] | tuple[bytes, ...],
    tag: str,
    extra: dict | None,
    rid: str,
) -> dict:
    """The paid part of `chat`, run under reserve `rid`; its ledger row settles that reserve."""
    rate_in, rate_out = TOKEN_USD.get(model, (1.25e-6, 4.25e-6))
    body_msgs = messages
    if images:
        last = dict(messages[-1])
        parts: list[dict] = [{"type": "text", "text": str(last.get("content", ""))}]
        for img in images:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64," + base64.b64encode(img).decode("ascii")
                    },
                }
            )
        last["content"] = parts
        body_msgs = [*messages[:-1], last]
    payload = {
        "model": model,
        "messages": body_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra:
        payload.update(extra)
    t0 = time.monotonic()
    try:
        resp = POST("/chat/completions", payload)
    except httpx.HTTPError as exc:
        raise ApiError(f"model API unreachable: {exc!r}") from exc
    _stop_on_budget(resp)
    if resp.status_code >= 400:
        raise ApiError(f"HTTP {resp.status_code} from the model API: {resp.text[:200]}")
    try:
        j = resp.json()
        text = str(j["choices"][0]["message"].get("content") or "")
        finish = j["choices"][0].get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ApiError(f"unexpected response shape ({exc!r})") from exc
    u = j.get("usage") or {}
    est = (
        float(u.get("prompt_tokens") or 0) * rate_in
        + float(u.get("completion_tokens") or 0) * rate_out
    )
    cache = resp.headers.get(CACHE_HEADER)
    if cache and "hit" in cache.lower():
        est = 0.0
    _ledger(
        {
            "ts": time.time(),
            "kind": "chat",
            "model": model,
            "tag": tag,
            "settles": rid,
            "est_usd": round(est, 6),
            "cache": cache,
            "prompt_tokens": u.get("prompt_tokens"),
            "completion_tokens": u.get("completion_tokens"),
            "finish": finish,
            "seconds": round(time.monotonic() - t0, 1),
        }
    )
    return {"text": text, "usage": u, "est_usd": est, "cache": cache, "finish": finish}


def _sam(content: list[dict], worst: float, tag: str, meta: dict | None = None) -> dict:
    rid = _reserve(worst, tag)
    try:
        return _sam_call(content, tag, meta, rid)
    except BaseException:
        _release(rid)
        raise


def _sam_call(content: list[dict], tag: str, meta: dict | None, rid: str) -> dict:
    """The paid part of `_sam`, run under reserve `rid`; its ledger row settles that reserve."""
    body = {
        "model": "sam-3.1",
        "stream": False,
        "store": False,
        "input": [{"type": "message", "role": "user", "content": content}],
    }
    if meta:
        body["metadata"] = meta
    t0 = time.monotonic()
    try:
        resp = POST("/responses", body, timeout=900.0)
    except httpx.HTTPError as exc:
        raise ApiError(f"model API unreachable: {exc!r}") from exc
    _stop_on_budget(resp)
    if resp.status_code >= 400:
        raise ApiError(f"HTTP {resp.status_code} from sam-3.1: {resp.text[:300]}")
    j = resp.json()
    try:
        text = j["output"][0]["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ApiError(f"unexpected sam-3.1 response shape ({exc!r})") from exc
    u = j.get("usage") or {}
    frames = u.get("video_frames_processed") or 0
    est = (
        max(SAM_MIN_FRAMES, frames) * SAM_FRAME_USD
        if frames or "input_video" in json.dumps(content)[:200000]
        else SAM_IMAGE_USD
    )
    cache = resp.headers.get(CACHE_HEADER)
    if cache and "hit" in cache.lower():
        est = 0.0
    _ledger(
        {
            "ts": time.time(),
            "kind": "sam",
            "tag": tag,
            "settles": rid,
            "est_usd": round(est, 6),
            "cache": cache,
            "frames": frames,
            "images": u.get("images_processed"),
            "seconds": round(time.monotonic() - t0, 1),
        }
    )
    return {"text": text, "usage": u, "est_usd": est, "cache": cache}


def sam_image(jpeg: bytes, prompt: str, tag: str = "") -> dict:
    content = [
        {"type": "input_text", "text": prompt},
        {
            "type": "input_image",
            "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
        },
    ]
    return _sam(content, SAM_IMAGE_USD, tag or "sam-image")


def sam_video(mp4: bytes, prompt: str, tag: str = "", frames_hint: int = 60) -> dict:
    content = [
        {"type": "input_text", "text": prompt},
        {
            "type": "input_video",
            "video_url": "data:video/mp4;base64," + base64.b64encode(mp4).decode("ascii"),
        },
    ]
    worst = max(SAM_MIN_FRAMES, 2 * frames_hint) * SAM_FRAME_USD
    return _sam(
        content,
        worst,
        tag or "sam-video",
        meta={"include_confidence": "true", "propagation_direction": "forward"},
    )
