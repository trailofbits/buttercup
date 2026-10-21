"""Tests for the dashboard's OrcaRouter provider endpoints.

The panel must never receive the credential itself, only its location and a
masked form, and it must only offer models the client can actually call.
"""

from collections.abc import Generator

import pytest
from buttercup.common import orcarouter
from buttercup.common.orcarouter import (
    CAPABILITY_CHAT,
    CAPABILITY_MULTIMODAL,
    ORCAROUTER_CHAT_CATALOG_URL,
    ORCAROUTER_KEY_PREFIX,
    CatalogSnapshot,
    OrcaRouterModel,
)
from fastapi.testclient import TestClient

from buttercup.orchestrator.ui.competition_api.main import app
from buttercup.orchestrator.ui.competition_api.services.orcarouter_service import OrcaRouterProviderService

FAKE_KEY = ORCAROUTER_KEY_PREFIX + "test-only-not-a-real-credential"
KEY_ENV = orcarouter.ORCAROUTER_API_KEY_ENV

MODELS = [
    OrcaRouterModel(
        id="vision/model",
        input_modalities=("text", "image"),
        output_modalities=("text",),
        supported_endpoint_types=("openai",),
    ),
    OrcaRouterModel(
        id="text/model",
        input_modalities=("text",),
        output_modalities=("text",),
        supported_endpoint_types=("anthropic",),
    ),
    OrcaRouterModel(id="unusable/model", supported_endpoint_types=("bedrock",)),
]


@pytest.fixture
def live_catalog(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Replace discovery with a fixed catalog so the tests stay hermetic."""
    monkeypatch.setenv(orcarouter.ORCAROUTER_API_KEY_ENV, FAKE_KEY)
    monkeypatch.setattr(
        orcarouter,
        "discover_models",
        lambda *args, **kwargs: CatalogSnapshot(models=list(MODELS), source="catalog"),
    )
    yield


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv(orcarouter.ORCAROUTER_API_KEY_ENV, FAKE_KEY)
    monkeypatch.setattr(
        "buttercup.orchestrator.ui.competition_api.services.orcarouter_service.discover_models",
        lambda *args, **kwargs: CatalogSnapshot(models=list(MODELS), source="catalog"),
    )
    with TestClient(app) as test_client:
        yield test_client


class TestProviderPayload:
    def test_names_the_provider_with_its_own_origins(self, client: TestClient) -> None:
        response = client.get("/v1/providers/orcarouter")
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "OrcaRouter"
        assert body["home_url"] == "https://www.orcarouter.ai"
        assert body["auth_origin"] == "https://www.orcarouter.ai"
        assert body["api_base"] == "https://api.orcarouter.ai/v1"
        assert body["catalog_url"] == ORCAROUTER_CHAT_CATALOG_URL

    def test_only_offers_models_the_client_can_call(self, client: TestClient) -> None:
        body = client.get("/v1/providers/orcarouter").json()
        assert [model["id"] for model in body["models"]] == ["vision/model", "text/model"]
        assert body["count"] == 2
        assert body["catalog"] == {"model_count": 3, "image_model_count": 1}

    def test_capability_filters_are_exposed_with_counts(self, client: TestClient) -> None:
        body = client.get("/v1/providers/orcarouter").json()
        counts = {capability["name"]: capability["count"] for capability in body["capabilities"]}
        assert counts == {CAPABILITY_CHAT: 2, CAPABILITY_MULTIMODAL: 1}
        assert all(capability["description"] for capability in body["capabilities"])

    def test_multimodal_capability_fails_closed(self, client: TestClient) -> None:
        body = client.get("/v1/providers/orcarouter", params={"capability": CAPABILITY_MULTIMODAL}).json()
        assert [model["id"] for model in body["models"]] == ["vision/model"]

    def test_unknown_capability_is_a_client_error(self, client: TestClient) -> None:
        assert client.get("/v1/providers/orcarouter", params={"capability": "embeddings"}).status_code == 400


class TestCredentialHandling:
    def test_returns_only_a_masked_key(self, client: TestClient) -> None:
        body = client.get("/v1/providers/orcarouter").json()
        authentication = body["authentication"]
        assert authentication["method"] == "api_key"
        assert authentication["header"] == "Authorization: Bearer"
        assert authentication["key_env"] == KEY_ENV
        assert authentication["configured"] is True
        assert authentication["masked_key"].startswith(ORCAROUTER_KEY_PREFIX)
        assert authentication["masked_key"].endswith(FAKE_KEY[-4:])
        assert FAKE_KEY not in response_text(client)

    def test_unconfigured_key_is_reported_without_a_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(orcarouter.ORCAROUTER_API_KEY_ENV, raising=False)
        monkeypatch.setattr(
            "buttercup.orchestrator.ui.competition_api.services.orcarouter_service.discover_models",
            lambda *args, **kwargs: CatalogSnapshot(models=list(MODELS), source="seed", error="no API key configured"),
        )
        with TestClient(app) as test_client:
            body = test_client.get("/v1/providers/orcarouter").json()
        assert body["authentication"]["configured"] is False
        assert body["authentication"]["masked_key"] is None


class TestModelsPayload:
    def test_models_endpoint_matches_the_provider_endpoint(self, client: TestClient) -> None:
        models = client.get("/v1/providers/orcarouter/models").json()
        provider = client.get("/v1/providers/orcarouter").json()
        assert models["models"] == provider["models"]
        assert models["capability"] == CAPABILITY_CHAT
        assert models["catalog_url"] == ORCAROUTER_CHAT_CATALOG_URL

    def test_models_endpoint_rejects_unknown_capability(self, client: TestClient) -> None:
        assert client.get("/v1/providers/orcarouter/models", params={"capability": "audio"}).status_code == 400


class TestFallback:
    def test_seed_fallback_is_reported_to_the_dashboard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(orcarouter.ORCAROUTER_API_KEY_ENV, FAKE_KEY)
        monkeypatch.setattr(
            "buttercup.orchestrator.ui.competition_api.services.orcarouter_service.discover_models",
            lambda *args, **kwargs: CatalogSnapshot(
                models=list(orcarouter.VERIFIED_SEED), source="seed", error="catalog request failed with HTTP 500"
            ),
        )
        with TestClient(app) as test_client:
            body = test_client.get("/v1/providers/orcarouter").json()
        assert body["source"] == "seed"
        assert "HTTP 500" in body["error"]
        assert body["count"] == len(orcarouter.VERIFIED_SEED)

    def test_service_rejects_unknown_capability_directly(self) -> None:
        with pytest.raises(ValueError):
            OrcaRouterProviderService().models_payload("embeddings")


def response_text(client: TestClient) -> str:
    return client.get("/v1/providers/orcarouter").text
