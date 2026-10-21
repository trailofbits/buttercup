"""Tests for the named OrcaRouter provider: identity, discovery, filters.

The catalog is authoritative, so every test that does not hit the live gateway
builds its payload from the same shape the gateway returns.
"""

import io
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from buttercup.common import orcarouter
from buttercup.common.orcarouter import (
    CAPABILITY_CHAT,
    CAPABILITY_MULTIMODAL,
    MAX_CATALOG_ITEMS,
    ORCAROUTER_API_BASE,
    ORCAROUTER_API_KEY_ENV,
    ORCAROUTER_AUTH_ORIGIN,
    ORCAROUTER_CHAT_CATALOG_URL,
    ORCAROUTER_HOME_URL,
    ORCAROUTER_KEY_PREFIX,
    VERIFIED_SEED,
    OrcaRouterCatalogError,
    OrcaRouterModel,
    api_key_from_env,
    create_orcarouter_llm,
    discover_models,
    fetch_catalog,
    mask_api_key,
    merge_with_seed,
    parse_catalog,
    select_models,
)

FAKE_KEY = ORCAROUTER_KEY_PREFIX + "test-only-not-a-real-credential"


def record(model_id: str, *, endpoints=None, inputs=None, outputs=None):
    payload = {"id": model_id, "supported_endpoint_types": endpoints if endpoints is not None else ["openai"]}
    if inputs is not None or outputs is not None:
        payload["architecture"] = {
            "input_modalities": inputs or [],
            "output_modalities": outputs or [],
        }
    return payload


def fake_urlopen(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=response)


class TestProviderIdentity:
    def test_origins_are_distinct_constants(self):
        assert ORCAROUTER_HOME_URL == "https://www.orcarouter.ai"
        assert ORCAROUTER_AUTH_ORIGIN == "https://www.orcarouter.ai"
        assert ORCAROUTER_API_BASE == "https://api.orcarouter.ai/v1"
        assert ORCAROUTER_CHAT_CATALOG_URL == "https://api.orcarouter.ai/v1/models?capability=chat"
        assert ORCAROUTER_API_KEY_ENV == "ORCAROUTER_API_KEY"
        assert ORCAROUTER_KEY_PREFIX == "sk-orca-"

    def test_verified_seed_is_bounded_and_covers_the_documented_defaults(self):
        ids = [model.id for model in VERIFIED_SEED]
        assert len(ids) == len(set(ids))
        assert 0 < len(VERIFIED_SEED) <= 8
        for expected in (
            "openai/gpt-5.5",
            "anthropic/claude-opus-4.8",
            "google/gemini-3.5-flash",
            "deepseek/deepseek-v4-pro",
            "orcarouter/auto",
        ):
            assert expected in ids
        gpt = next(model for model in VERIFIED_SEED if model.id == "openai/gpt-5.5")
        assert gpt.reasoning_efforts == ("low", "medium", "high", "xhigh")
        assert all(model.selectable for model in VERIFIED_SEED)


class TestParseCatalog:
    def test_parses_architecture_and_endpoint_types(self):
        models = parse_catalog(
            {
                "data": [
                    record(
                        "vision/model", endpoints=["openai", "anthropic"], inputs=["text", "image"], outputs=["text"]
                    ),
                    record("plain/model", endpoints=["openai"], inputs=["text"], outputs=["text"]),
                ]
            }
        )
        assert [model.id for model in models] == ["vision/model", "plain/model"]
        assert models[0].multimodal is True
        assert models[1].multimodal is False
        assert models[0].supported_endpoint_types == ("openai", "anthropic")

    def test_rejects_non_object_payload_and_missing_data(self):
        with pytest.raises(OrcaRouterCatalogError):
            parse_catalog([])
        with pytest.raises(OrcaRouterCatalogError):
            parse_catalog({"object": "list"})

    def test_drops_unusable_records_and_duplicates(self):
        models = parse_catalog(
            {
                "data": [
                    "not-a-record",
                    {"id": ""},
                    {"id": "x" * (orcarouter.MAX_MODEL_ID_LENGTH + 1)},
                    {"id": "bad/architecture", "architecture": "image"},
                    record("kept/model"),
                    record("kept/model"),
                ]
            }
        )
        assert [model.id for model in models] == ["kept/model"]

    def test_empty_or_oversized_catalogs_raise(self):
        with pytest.raises(OrcaRouterCatalogError):
            parse_catalog({"data": [{"id": ""}]})
        with pytest.raises(OrcaRouterCatalogError):
            parse_catalog({"data": [record(f"model/{i}") for i in range(MAX_CATALOG_ITEMS + 1)]})

    def test_truncates_unbounded_metadata(self):
        models = parse_catalog(
            {
                "data": [
                    record(
                        "noisy/model",
                        endpoints=[f"dialect-{i}" for i in range(50)],
                        inputs=["text"] * 1 + ["image"] + [f"modality-{i}" for i in range(50)],
                    )
                ]
            }
        )
        assert len(models[0].supported_endpoint_types) == orcarouter.MAX_ENDPOINT_TYPES
        assert len(models[0].input_modalities) == orcarouter.MAX_MODALITIES


class TestCapabilityFilters:
    def test_chat_requires_a_supported_endpoint_dialect(self):
        models = [
            OrcaRouterModel(id="good", supported_endpoint_types=("openai",)),
            OrcaRouterModel(id="unsupported", supported_endpoint_types=("bedrock",)),
            OrcaRouterModel(id="unknown", supported_endpoint_types=()),
        ]
        assert [model.id for model in select_models(models, capability=CAPABILITY_CHAT)] == ["good"]

    def test_multimodal_fails_closed_without_modality_metadata(self):
        models = [
            OrcaRouterModel(id="image", input_modalities=("text", "image"), supported_endpoint_types=("openai",)),
            OrcaRouterModel(id="text-only", input_modalities=("text",), supported_endpoint_types=("openai",)),
            OrcaRouterModel(id="no-metadata", supported_endpoint_types=("openai",)),
        ]
        assert [model.id for model in select_models(models, capability=CAPABILITY_MULTIMODAL)] == ["image"]
        assert len(select_models(models, capability=CAPABILITY_CHAT)) == 3

    def test_unknown_capability_is_rejected(self):
        with pytest.raises(ValueError):
            select_models(VERIFIED_SEED, capability="embeddings")

    def test_merge_keeps_seed_metadata_for_live_records(self):
        live = [OrcaRouterModel(id="openai/gpt-5.5", supported_endpoint_types=("openai",))]
        merged = merge_with_seed(live)
        assert merged[0].reasoning_efforts == ("low", "medium", "high", "xhigh")
        assert merged[0].input_modalities == ("text",)
        assert merged[0].source == "catalog"


class TestFetchCatalog:
    def test_sends_bearer_token_to_the_chat_catalog(self):
        payload = {"data": [record("live/model")]}
        with patch.object(orcarouter.urllib.request, "urlopen", fake_urlopen(payload)) as urlopen:
            models = fetch_catalog(FAKE_KEY)
        request = urlopen.call_args.args[0]
        assert request.full_url == ORCAROUTER_CHAT_CATALOG_URL
        assert request.get_header("Authorization") == f"Bearer {FAKE_KEY}"
        assert [model.id for model in models] == ["live/model"]

    def test_http_error_reports_status_without_echoing_the_key(self):
        error = urllib.error.HTTPError(ORCAROUTER_CHAT_CATALOG_URL, 403, "Forbidden", {}, io.BytesIO(b""))
        with patch.object(orcarouter.urllib.request, "urlopen", MagicMock(side_effect=error)):
            with pytest.raises(OrcaRouterCatalogError) as excinfo:
                fetch_catalog(FAKE_KEY)
        message = str(excinfo.value)
        assert "HTTP 403" in message
        assert FAKE_KEY not in message

    def test_network_failure_is_reported(self):
        with patch.object(
            orcarouter.urllib.request,
            "urlopen",
            MagicMock(side_effect=urllib.error.URLError("unreachable")),
        ):
            with pytest.raises(OrcaRouterCatalogError) as excinfo:
                fetch_catalog(FAKE_KEY)
        assert FAKE_KEY not in str(excinfo.value)

    def test_oversized_and_invalid_responses_are_rejected(self):
        oversized = MagicMock()
        oversized.read.return_value = b"x" * (orcarouter.MAX_CATALOG_BYTES + 1)
        oversized.__enter__ = MagicMock(return_value=oversized)
        oversized.__exit__ = MagicMock(return_value=False)
        with patch.object(orcarouter.urllib.request, "urlopen", MagicMock(return_value=oversized)):
            with pytest.raises(OrcaRouterCatalogError):
                fetch_catalog(FAKE_KEY)
        invalid = fake_urlopen({"data": []})
        invalid.return_value.read.return_value = b"not json"
        with patch.object(orcarouter.urllib.request, "urlopen", invalid):
            with pytest.raises(OrcaRouterCatalogError):
                fetch_catalog(FAKE_KEY)

    def test_requires_a_key_and_supports_only_chat_catalog(self):
        with pytest.raises(OrcaRouterCatalogError):
            fetch_catalog("")
        with pytest.raises(OrcaRouterCatalogError):
            fetch_catalog(FAKE_KEY, capability=CAPABILITY_MULTIMODAL)


class TestDiscovery:
    def test_without_a_key_the_verified_seed_is_used(self, monkeypatch):
        monkeypatch.delenv(ORCAROUTER_API_KEY_ENV, raising=False)
        snapshot = discover_models()
        assert snapshot.source == "seed"
        assert snapshot.error == "no API key configured"
        assert snapshot.ids == [model.id for model in VERIFIED_SEED]

    def test_failure_falls_back_without_losing_metadata(self, monkeypatch):
        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, FAKE_KEY)
        with patch.object(orcarouter, "fetch_catalog", MagicMock(side_effect=OrcaRouterCatalogError("HTTP 500"))):
            snapshot = discover_models()
        assert snapshot.source == "seed"
        assert snapshot.error == "HTTP 500"
        seed_gpt = next(model for model in snapshot.models if model.id == "openai/gpt-5.5")
        assert seed_gpt.reasoning_efforts == ("low", "medium", "high", "xhigh")

    def test_live_catalog_wins_and_is_filtered_per_capability(self, monkeypatch):
        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, FAKE_KEY)
        live = [
            OrcaRouterModel(
                id="vision/model", input_modalities=("text", "image"), supported_endpoint_types=("openai",)
            ),
            OrcaRouterModel(id="text/model", input_modalities=("text",), supported_endpoint_types=("anthropic",)),
            OrcaRouterModel(id="ignored/model", supported_endpoint_types=("bedrock",)),
        ]
        with patch.object(orcarouter, "fetch_catalog", MagicMock(return_value=live)):
            chat = discover_models()
            multimodal = discover_models(capability=CAPABILITY_MULTIMODAL)
        assert chat.source == "catalog"
        assert chat.error is None
        assert chat.ids == ["vision/model", "text/model"]
        assert multimodal.ids == ["vision/model"]

    def test_empty_live_catalog_falls_back_to_seed(self, monkeypatch):
        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, FAKE_KEY)
        with patch.object(
            orcarouter,
            "fetch_catalog",
            MagicMock(return_value=[OrcaRouterModel(id="bedrock-only", supported_endpoint_types=("bedrock",))]),
        ):
            snapshot = discover_models()
        assert snapshot.source == "seed"
        assert snapshot.error == "catalog offered no usable model"

    def test_api_key_is_read_from_the_environment_only(self, monkeypatch):
        monkeypatch.delenv(ORCAROUTER_API_KEY_ENV, raising=False)
        assert api_key_from_env() is None
        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, FAKE_KEY)
        assert api_key_from_env() == FAKE_KEY


class TestMasking:
    def test_mask_never_returns_the_full_key(self):
        masked = mask_api_key(FAKE_KEY)
        assert masked.startswith(ORCAROUTER_KEY_PREFIX)
        assert masked.endswith(FAKE_KEY[-4:])
        assert FAKE_KEY not in masked
        assert mask_api_key("") == ""

    def test_short_key_reveals_nothing(self):
        assert mask_api_key("sk-orca-1") == "sk-orca-…"


class TestChatClient:
    def test_requires_a_configured_key(self, monkeypatch):
        monkeypatch.delenv(ORCAROUTER_API_KEY_ENV, raising=False)
        with pytest.raises(ValueError):
            create_orcarouter_llm("deepseek/deepseek-v4-pro")

    def test_points_the_client_at_the_orcarouter_endpoint(self, monkeypatch):
        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, FAKE_KEY)
        llm = create_orcarouter_llm("deepseek/deepseek-v4-pro")
        assert str(llm.openai_api_base) == ORCAROUTER_API_BASE
        assert llm.model_name == "deepseek/deepseek-v4-pro"
        assert llm.openai_api_key.get_secret_value() == FAKE_KEY


@pytest.mark.skipif(not os.environ.get(ORCAROUTER_API_KEY_ENV), reason="needs ORCAROUTER_API_KEY")
class TestLiveGateway:
    """Live checks. They read the real gateway only when a key is present."""

    def test_live_catalog_lists_the_default_chat_models(self):
        snapshot = discover_models()
        assert snapshot.source == "catalog", snapshot.error
        assert 0 < len(snapshot.models) <= orcarouter.MAX_CATALOG_ITEMS
        assert "deepseek/deepseek-v4-pro" in snapshot.ids
        assert all(model.selectable for model in snapshot.models)

    def test_live_chat_completion(self):
        llm = create_orcarouter_llm("deepseek/deepseek-v4-pro", timeout=60.0)
        reply = llm.invoke("Reply with the single word: ready")
        assert isinstance(reply.content, str)
        assert reply.content.strip()
