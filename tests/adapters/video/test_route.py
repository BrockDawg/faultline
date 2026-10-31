"""The forklift client sends Meta's open-weight models to Baseten when a Baseten key is set."""

from __future__ import annotations

import pytest

from faultline.adapters.video import client


@pytest.fixture
def plain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BASETEN_API_KEY", "BASETEN_API_BASE", "STEWARD_ENV_FILE", "MODEL_API_BASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "meta-test-key")


def test_open_weight_model_goes_to_baseten(
    plain_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-test-key")
    assert client.route("meta-models/muse-spark-open-1026") == (
        "baseten-test-key",
        client.BASETEN_BASE,
    )
    assert client.route("muse-wonder-1.0") == ("meta-test-key", client.DEFAULT_BASE)
    assert client.route("sam-3.1") == ("meta-test-key", client.DEFAULT_BASE)


def test_baseten_base_can_be_overridden(plain_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-test-key")
    monkeypatch.setenv("BASETEN_API_BASE", "https://example.test/v1/")
    assert client.route("meta-models/muse-spark-open-1026") == (
        "baseten-test-key",
        "https://example.test/v1",
    )


def test_without_a_baseten_key_everything_uses_the_model_api_base(
    plain_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_API_BASE", "http://127.0.0.1:8765/v1")
    assert client.route("meta-models/muse-spark-open-1026") == (
        "meta-test-key",
        "http://127.0.0.1:8765/v1",
    )


def test_post_routes_by_the_payload_model(plain_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-test-key")
    seen: list[tuple[str, str]] = []

    def fake_post(url: str, headers: dict, json: dict, timeout: float) -> None:  # noqa: A002
        seen.append((url, headers["Authorization"]))

    monkeypatch.setattr(client.httpx, "post", fake_post)
    client._post("/chat/completions", {"model": "meta-models/muse-spark-open-1026"})
    client._post("/responses", {"model": "sam-3.1"})
    assert seen == [
        (client.BASETEN_BASE + "/chat/completions", "Bearer baseten-test-key"),
        (client.DEFAULT_BASE + "/responses", "Bearer meta-test-key"),
    ]
