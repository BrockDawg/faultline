"""The forklift client's spend cap: read from FAULTLINE_CAP_USD, checked and reserved under a lock,
so two callers at the cap pay once, and a refused or failed call leaves no reserve counting.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from faultline.adapters.video import client

BODY = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
}
MSGS = [{"role": "user", "content": "hi"}]
MODEL = "muse-spark-1.3"


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(client, "LEDGER", path)
    monkeypatch.delenv("FAULTLINE_CAP_USD", raising=False)
    return path


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.startswith("{")]


def seed(path: Path, usd: float) -> None:
    path.write_text(
        json.dumps({"ts": time.time(), "kind": "chat", "est_usd": usd}) + "\n", encoding="utf-8"
    )


def test_the_cap_reads_the_env(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAULTLINE_CAP_USD", "10")
    assert client.cap_usd() == 10.0


def test_the_default_cap_is_unchanged(ledger: Path) -> None:
    assert client.LOCAL_CAP_USD == 4.90
    assert client.cap_usd() == 4.90


@pytest.mark.parametrize("raw", ["ten", "-1", "nan", "inf"])
def test_a_bad_cap_is_refused_before_send(
    ledger: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("FAULTLINE_CAP_USD", raw)
    monkeypatch.setattr(client, "POST", lambda *_a, **_k: pytest.fail("sent past a bad cap"))
    with pytest.raises(client.ApiError, match="FAULTLINE_CAP_USD"):
        client.chat(MSGS, model=MODEL, worst_usd=0.01)
    assert rows(ledger) == []


def test_refusal_before_send_writes_no_reserve(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_CAP_USD", "1.00")
    seed(ledger, 0.95)
    monkeypatch.setattr(client, "POST", lambda *_a, **_k: pytest.fail("sent past the cap"))
    with pytest.raises(client.BudgetSpent, match=r"\$1\.00"):
        client.chat(MSGS, model=MODEL, worst_usd=0.10)
    assert isinstance(client.BudgetSpent("x"), SystemExit)
    assert [r.get("kind") for r in rows(ledger)] == ["chat"]
    assert client.spent() == pytest.approx(0.95)


def test_old_rows_sum_the_same_and_a_settled_reserve_counts_once(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = [
        {"ts": time.time(), "kind": "chat", "est_usd": 0.25},
        {"ts": time.time(), "kind": "sam", "est_usd": 0.5},
        {"ts": 1.0, "kind": "chat", "est_usd": 9.0},
    ]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in old) + "not json\n", encoding="utf-8")
    assert client.spent() == pytest.approx(9.75)
    assert client.spent(client.WAVE_START_TS) == pytest.approx(0.75)
    monkeypatch.setattr(client, "POST", lambda *_a, **_k: httpx.Response(200, json=BODY))
    got = client.chat(MSGS, model=MODEL, worst_usd=2.0)
    assert client.spent(client.WAVE_START_TS) == pytest.approx(0.75 + got["est_usd"], abs=1e-6)
    kinds = [r.get("kind") for r in rows(ledger)[3:]]
    assert kinds == ["reserve", "chat"]
    assert rows(ledger)[-1]["settles"] == rows(ledger)[-2]["id"]


def race(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, list[BaseException]]:
    """Two threads ask for one call each while the first call is still in flight."""
    sent: list[int] = []
    in_flight = threading.Event()

    def slow_post(_path: str, _payload: dict, timeout: float = 600.0) -> httpx.Response:
        sent.append(1)
        in_flight.set()
        time.sleep(0.3)
        return httpx.Response(200, json=BODY)

    monkeypatch.setattr(client, "POST", slow_post)
    errors: list[BaseException] = []

    def one() -> None:
        try:
            client.chat(MSGS, model=MODEL, worst_usd=1.0)
        except BaseException as exc:  # noqa: BLE001 - BudgetSpent is a SystemExit
            errors.append(exc)

    first = threading.Thread(target=one)
    first.start()
    assert in_flight.wait(5)
    second = threading.Thread(target=one)
    second.start()
    first.join(10)
    second.join(10)
    return len(sent), errors


@pytest.mark.parametrize(("cap", "already"), [("1.5", None), ("4.5", 3.0)])
def test_two_callers_racing_at_the_cap_pay_once(
    ledger: Path, monkeypatch: pytest.MonkeyPatch, cap: str, already: float | None
) -> None:
    """Cold start (empty ledger) and steady state (a ledger one call under the cap)."""
    monkeypatch.setenv("FAULTLINE_CAP_USD", cap)
    if already is not None:
        seed(ledger, already)
    n_sent, errors = race(ledger, monkeypatch)
    assert n_sent == 1
    assert len(errors) == 1 and isinstance(errors[0], client.BudgetSpent)
    kinds = [r.get("kind") for r in rows(ledger)]
    assert kinds.count("reserve") == 1 and kinds[-1] == "chat"


def test_the_lock_file_sits_beside_the_ledger(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client, "POST", lambda *_a, **_k: httpx.Response(200, json=BODY))
    client.chat(MSGS, model=MODEL, worst_usd=0.5)
    assert (ledger.parent / "ledger.jsonl.lock").exists()


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError("down"),
        httpx.Response(500, text="boom"),
        httpx.Response(429, json={"error": {"type": "budget", "message": "budget spent"}}),
        httpx.Response(200, json={"nope": 1}),
    ],
)
def test_a_failed_call_releases_its_reserve(
    ledger: Path, monkeypatch: pytest.MonkeyPatch, outcome: object
) -> None:
    monkeypatch.setenv("FAULTLINE_CAP_USD", "1.5")

    def post(_path: str, _payload: dict, timeout: float = 600.0) -> httpx.Response:
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, httpx.Response)
        return outcome

    monkeypatch.setattr(client, "POST", post)
    with pytest.raises((client.ApiError, client.BudgetSpent)):
        client.chat(MSGS, model=MODEL, worst_usd=1.0)
    got = rows(ledger)
    assert [r["kind"] for r in got] == ["reserve", "release"]
    assert got[1]["settles"] == got[0]["id"]
    assert client.spent() == 0.0
    # the released dollar is free again: a full-size call still fits under the cap
    monkeypatch.setattr(client, "POST", lambda *_a, **_k: httpx.Response(200, json=BODY))
    client.chat(MSGS, model=MODEL, worst_usd=1.0)


def test_a_sam_call_reserves_and_settles(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"output": [{"content": [{"text": "[]"}]}], "usage": {"images_processed": 1}}
    monkeypatch.setattr(client, "POST", lambda *_a, **_k: httpx.Response(200, json=reply))
    client.sam_image(b"\xff\xd8", "a person")
    got = rows(ledger)
    assert [r["kind"] for r in got] == ["reserve", "sam"]
    assert got[1]["settles"] == got[0]["id"]
    assert client.spent() == pytest.approx(client.SAM_IMAGE_USD)
