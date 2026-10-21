"""OrcaRouter provider: naming, bounded model discovery and capability filters.

OrcaRouter is an OpenAI-compatible AI gateway.  Buttercup reaches it through the
same LiteLLM proxy it uses for every other provider, so the provider definition
lives in ``litellm/litellm_config.yaml`` (mirrored in the Kubernetes values) and
the selectable model names live in :class:`buttercup.common.llm.ButtercupLLM`.

This module owns the parts that cannot be expressed in YAML:

* the canonical provider identity and the two distinct public origins (the auth
  origin is never derived from the inference origin, and vice versa);
* bounded live discovery of the authoritative chat catalog
  (``GET https://api.orcarouter.ai/v1/models?capability=chat``);
* capability filters so a selector can never offer a model the client cannot
  actually speak (unsupported endpoint dialects and missing modality metadata
  fail closed);
* a small verified fallback seed so a fresh installation still starts when the
  catalog endpoint is slow or unavailable.

Secrets are only ever read from the environment (``ORCAROUTER_API_KEY``) or
passed in explicitly by a caller that holds them in memory.  Nothing here logs,
returns or formats a key.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

ORCAROUTER_NAME = "OrcaRouter"
ORCAROUTER_HOME_URL = "https://www.orcarouter.ai"
# Authentication and key management live on the www origin; inference and model
# discovery live on the api origin.  They are deliberately independent constants.
ORCAROUTER_AUTH_ORIGIN = "https://www.orcarouter.ai"
ORCAROUTER_API_BASE = "https://api.orcarouter.ai/v1"
ORCAROUTER_CHAT_CATALOG_URL = f"{ORCAROUTER_API_BASE}/models?capability=chat"
ORCAROUTER_API_KEY_ENV = "ORCAROUTER_API_KEY"
ORCAROUTER_KEY_PREFIX = "sk-orca-"
ORCAROUTER_DOCS_URL = "https://www.orcarouter.ai/docs"

#: Endpoint dialects the OpenAI-compatible client used by Buttercup can speak.
#: A catalog record advertising none of these is not selectable.
SUPPORTED_ENDPOINT_TYPES = frozenset({"openai", "openai-response", "anthropic", "gemini"})

#: Capabilities the gateway currently advertises for chat models.
CAPABILITY_CHAT = "chat"
CAPABILITY_MULTIMODAL = "multimodal"

#: Hard bounds so a catalog response cannot consume unbounded memory or offer an
#: unbounded number of options.
MAX_CATALOG_BYTES = 1 << 20
MAX_CATALOG_ITEMS = 500
CATALOG_TIMEOUT_SECONDS = 10.0
MAX_MODEL_ID_LENGTH = 200
MAX_ENDPOINT_TYPES = 8
MAX_MODALITIES = 8


class OrcaRouterCatalogError(RuntimeError):
    """Raised when the authoritative catalog cannot be read or is malformed."""


@dataclass(frozen=True)
class OrcaRouterModel:
    """One selectable OrcaRouter model, with the metadata a selector needs."""

    id: str
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    supported_endpoint_types: tuple[str, ...] = ()
    reasoning_efforts: tuple[str, ...] = ()
    source: str = "catalog"

    @property
    def multimodal(self) -> bool:
        """True only when the catalog explicitly advertises image input."""
        return "image" in self.input_modalities

    @property
    def selectable(self) -> bool:
        """True when the client can speak at least one advertised endpoint dialect."""
        return bool(SUPPORTED_ENDPOINT_TYPES.intersection(self.supported_endpoint_types))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input_modalities": list(self.input_modalities),
            "output_modalities": list(self.output_modalities),
            "supported_endpoint_types": list(self.supported_endpoint_types),
            "reasoning_efforts": list(self.reasoning_efforts),
            "multimodal": self.multimodal,
            "source": self.source,
        }


#: Small, verified seed used only when live discovery fails.  Reasoning ladders
#: and modality metadata are kept here so discovery never reduces a known model.
VERIFIED_SEED: tuple[OrcaRouterModel, ...] = (
    OrcaRouterModel(
        id="openai/gpt-5.5",
        input_modalities=("text",),
        output_modalities=("text",),
        supported_endpoint_types=("openai", "openai-response"),
        reasoning_efforts=("low", "medium", "high", "xhigh"),
        source="seed",
    ),
    OrcaRouterModel(
        id="anthropic/claude-opus-4.8",
        input_modalities=("text",),
        output_modalities=("text",),
        supported_endpoint_types=("anthropic",),
        source="seed",
    ),
    OrcaRouterModel(
        id="google/gemini-3.5-flash",
        input_modalities=("text",),
        output_modalities=("text",),
        supported_endpoint_types=("gemini",),
        source="seed",
    ),
    OrcaRouterModel(
        id="deepseek/deepseek-v4-pro",
        input_modalities=("text",),
        output_modalities=("text",),
        supported_endpoint_types=("openai", "openai-response"),
        source="seed",
    ),
    OrcaRouterModel(
        id="orcarouter/auto",
        input_modalities=("text",),
        output_modalities=("text",),
        supported_endpoint_types=("openai", "openai-response", "anthropic", "gemini"),
        source="seed",
    ),
)

_SEED_BY_ID = {model.id: model for model in VERIFIED_SEED}


def _string_tuple(value: Any, limit: int) -> tuple[str, ...]:
    """Normalize a JSON list of short strings; anything else yields an empty tuple."""
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and 0 < len(item) <= 64 and item not in items:
            items.append(item)
        if len(items) >= limit:
            break
    return tuple(items)


def model_from_record(record: Any) -> OrcaRouterModel | None:
    """Convert one catalog record into a model, or ``None`` when the shape is not accepted."""
    if not isinstance(record, dict):
        return None
    model_id = record.get("id")
    if not isinstance(model_id, str):
        return None
    model_id = model_id.strip()
    if not model_id or len(model_id) > MAX_MODEL_ID_LENGTH:
        return None
    architecture = record.get("architecture")
    if architecture is not None and not isinstance(architecture, dict):
        return None
    architecture = architecture or {}
    # A live record that matches a verified seed entry inherits its reasoning
    # ladder, so discovery cannot silently strip a known capability.
    seed = _SEED_BY_ID.get(model_id)
    return OrcaRouterModel(
        id=model_id,
        input_modalities=_string_tuple(architecture.get("input_modalities"), MAX_MODALITIES),
        output_modalities=_string_tuple(architecture.get("output_modalities"), MAX_MODALITIES),
        supported_endpoint_types=_string_tuple(record.get("supported_endpoint_types"), MAX_ENDPOINT_TYPES),
        reasoning_efforts=seed.reasoning_efforts if seed else (),
        source="catalog",
    )


def parse_catalog(payload: Any) -> list[OrcaRouterModel]:
    """Parse a catalog payload, applying every bound and dropping unusable records."""
    if not isinstance(payload, dict):
        raise OrcaRouterCatalogError("catalog payload is not an object")
    records = payload.get("data")
    if not isinstance(records, list):
        raise OrcaRouterCatalogError("catalog payload has no data list")
    if len(records) > MAX_CATALOG_ITEMS:
        raise OrcaRouterCatalogError("catalog advertised too many models")
    models: list[OrcaRouterModel] = []
    seen: set[str] = set()
    for record in records:
        model = model_from_record(record)
        if model is None or model.id in seen:
            continue
        seen.add(model.id)
        models.append(model)
    if not models:
        raise OrcaRouterCatalogError("catalog advertised no usable models")
    return models


def fetch_catalog(
    api_key: str,
    *,
    capability: str = CAPABILITY_CHAT,
    timeout: float = CATALOG_TIMEOUT_SECONDS,
    url: str = ORCAROUTER_CHAT_CATALOG_URL,
) -> list[OrcaRouterModel]:
    """Fetch and parse the authoritative catalog with a bounded response size."""
    if capability != CAPABILITY_CHAT:
        raise OrcaRouterCatalogError(f"unsupported catalog capability: {capability}")
    if not api_key:
        raise OrcaRouterCatalogError("no OrcaRouter API key configured")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_CATALOG_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # The status code is safe to report; the body may echo request details.
        raise OrcaRouterCatalogError(f"catalog request failed with HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise OrcaRouterCatalogError(f"catalog request failed: {type(exc).__name__}") from None
    if len(raw) > MAX_CATALOG_BYTES:
        raise OrcaRouterCatalogError("catalog response exceeded the size bound")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise OrcaRouterCatalogError("catalog response was not valid JSON") from None
    models = parse_catalog(payload)
    return models


def merge_with_seed(models: Iterable[OrcaRouterModel]) -> list[OrcaRouterModel]:
    """Keep verified seed metadata for models the live catalog also advertises."""
    merged: list[OrcaRouterModel] = []
    for model in models:
        seed = _SEED_BY_ID.get(model.id)
        if seed is None:
            merged.append(model)
            continue
        merged.append(
            OrcaRouterModel(
                id=model.id,
                input_modalities=model.input_modalities or seed.input_modalities,
                output_modalities=model.output_modalities or seed.output_modalities,
                supported_endpoint_types=model.supported_endpoint_types or seed.supported_endpoint_types,
                reasoning_efforts=seed.reasoning_efforts,
                source=model.source,
            )
        )
    return merged


def select_models(
    models: Iterable[OrcaRouterModel],
    *,
    capability: str = CAPABILITY_CHAT,
) -> list[OrcaRouterModel]:
    """Return the models a selector may offer for ``capability``.

    ``chat`` offers every model that speaks a supported endpoint dialect.
    ``multimodal`` additionally requires the catalog to advertise image input:
    a record without modality metadata fails closed and is never offered.
    """
    if capability not in (CAPABILITY_CHAT, CAPABILITY_MULTIMODAL):
        raise ValueError(f"unsupported capability: {capability}")
    selected = [model for model in models if model.selectable]
    if capability == CAPABILITY_MULTIMODAL:
        selected = [model for model in selected if model.multimodal]
    return selected


@dataclass(frozen=True)
class CatalogSnapshot:
    """The outcome of one discovery attempt: live catalog, or the verified seed."""

    models: list[OrcaRouterModel] = field(default_factory=list)
    source: str = "seed"
    error: str | None = None

    @property
    def ids(self) -> list[str]:
        return [model.id for model in self.models]


def discover_models(
    api_key: str | None = None,
    *,
    capability: str = CAPABILITY_CHAT,
    timeout: float = CATALOG_TIMEOUT_SECONDS,
) -> CatalogSnapshot:
    """Discover models, falling back to the verified seed without losing metadata."""
    api_key = api_key or os.environ.get(ORCAROUTER_API_KEY_ENV, "")
    seed = select_models(VERIFIED_SEED, capability=capability)
    if not api_key:
        return CatalogSnapshot(models=seed, source="seed", error="no API key configured")
    try:
        models = fetch_catalog(api_key, capability=CAPABILITY_CHAT, timeout=timeout)
    except OrcaRouterCatalogError as exc:
        logger.warning("OrcaRouter model discovery failed, using verified seed: %s", exc)
        return CatalogSnapshot(models=seed, source="seed", error=str(exc))
    live = select_models(merge_with_seed(models), capability=capability)
    if not live:
        return CatalogSnapshot(models=seed, source="seed", error="catalog offered no usable model")
    return CatalogSnapshot(models=live, source="catalog")


def api_key_from_env() -> str | None:
    """Return the configured OrcaRouter key, if any. The value is never logged."""
    return os.environ.get(ORCAROUTER_API_KEY_ENV) or None


def create_orcarouter_llm(
    model_name: str,
    *,
    api_key: str | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Create a chat model bound to the named OrcaRouter provider.

    In a deployed Buttercup the agents go through the LiteLLM proxy, whose
    model list contains the ``orcarouter-*`` entries defined in
    ``litellm/litellm_config.yaml``.  This factory is the direct client for the
    same provider: it talks to the OpenAI-compatible inference origin with the
    OrcaRouter key and is what the dashboard and the live test use, so a key can
    be validated without deploying LiteLLM.
    """
    key = api_key or os.environ.get(ORCAROUTER_API_KEY_ENV)
    if not key:
        raise ValueError(f"{ORCAROUTER_API_KEY_ENV} is not configured")
    # Imported here so the discovery helpers above stay importable in a minimal
    # environment (the dashboard only needs the catalog, not a chat client).
    from langchain_openai.chat_models import ChatOpenAI
    from pydantic import SecretStr

    return ChatOpenAI(
        model=model_name,
        base_url=ORCAROUTER_API_BASE,
        api_key=SecretStr(key),
        timeout=kwargs.pop("timeout", 120.0),
        max_retries=kwargs.pop("max_retries", 0),
        **kwargs,
    )


def mask_api_key(api_key: str) -> str:
    """Render a key as a short prefix plus its last four characters."""
    if not api_key:
        return ""
    tail = api_key[-4:] if len(api_key) > len(ORCAROUTER_KEY_PREFIX) + 4 else ""
    return f"{ORCAROUTER_KEY_PREFIX}…{tail}" if tail else f"{ORCAROUTER_KEY_PREFIX}…"
