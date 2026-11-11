"""The forklift client's cache header and budget stop: no header is a miss, so spend counts."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from faultline.adapters.video import client

BODY = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
}


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(client, "LEDGER", path)
    return path


def answer(monkeypatch: pytest.MonkeyPatch, resp: httpx.Response) -> None:
    monkeypatch.setattr(client, "POST", lambda _path, _payload, timeout=600.0: resp)


@pytest.mark.parametrize(("header", "counted"), [(None, True), ("miss", True), ("hit", False)])
def test_no_cache_header_is_a_miss_and_its_spend_counts(
    ledger: Path, monkeypatch: pytest.MonkeyPatch, header: str | None, counted: bool
) -> None:
    headers = {client.CACHE_HEADER: header} if header is not None else None
    answer(monkeypatch, httpx.Response(200, json=BODY, headers=headers))
    got = client.chat([{"role": "user", "content": "hi"}], model="muse-spark-1.3")
    assert got["cache"] == header
    assert (got["est_usd"] > 0) is counted
    assert client.spent() == pytest.approx(got["est_usd"], abs=1e-6)


def test_the_cache_header_has_a_neutral_name() -> None:
    assert client.CACHE_HEADER == "x-faultline-cache"


def test_a_budget_429_stops_the_run(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"error": {"type": "budget_spent", "message": "token budget spent: $5.00"}}
    answer(monkeypatch, httpx.Response(429, json=body))
    with pytest.raises(client.BudgetSpent, match="token budget spent"):
        client.chat([{"role": "user", "content": "hi"}], model="muse-spark-1.3")


def test_a_429_without_budget_is_an_api_error(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer(monkeypatch, httpx.Response(429, json={"error": {"message": "slow down"}}))
    with pytest.raises(client.ApiError, match="HTTP 429"):
        client.chat([{"role": "user", "content": "hi"}], model="muse-spark-1.3")
