"""Dashboard view of the named OrcaRouter provider.

The dashboard never holds the API key itself: it is read from the process
environment, handed to :mod:`buttercup.common.orcarouter` for discovery, and
only the masked form is ever returned to the browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from buttercup.common.orcarouter import (
    CAPABILITY_CHAT,
    CAPABILITY_MULTIMODAL,
    ORCAROUTER_API_BASE,
    ORCAROUTER_API_KEY_ENV,
    ORCAROUTER_AUTH_ORIGIN,
    ORCAROUTER_CHAT_CATALOG_URL,
    ORCAROUTER_DOCS_URL,
    ORCAROUTER_HOME_URL,
    ORCAROUTER_NAME,
    OrcaRouterModel,
    api_key_from_env,
    discover_models,
    mask_api_key,
    select_models,
)

#: Capabilities the dashboard exposes as model selectors.
CATALOG_CAPABILITIES = (CAPABILITY_CHAT, CAPABILITY_MULTIMODAL)

#: Short, user-facing description of each capability filter.
CAPABILITY_DESCRIPTIONS = {
    CAPABILITY_CHAT: "Chat models that speak an endpoint dialect Buttercup can call.",
    CAPABILITY_MULTIMODAL: "Chat models whose catalog record advertises image input.",
}


@dataclass(frozen=True)
class CatalogView:
    """One catalog read, plus the filters a selector applies to it."""

    models: list[OrcaRouterModel]
    source: str
    error: str | None = None

    def for_capability(self, capability: str) -> list[OrcaRouterModel]:
        if capability not in CATALOG_CAPABILITIES:
            raise ValueError(f"unsupported capability: {capability}")
        return select_models(self.models, capability=capability)

    @property
    def image_model_count(self) -> int:
        return sum(1 for model in self.models if model.multimodal)


class OrcaRouterProviderService:
    """Read-only provider view for the competition API dashboard."""

    def __init__(self, catalog_timeout: float | None = None) -> None:
        self._catalog_timeout = catalog_timeout

    def catalog(self) -> CatalogView:
        """Read the authoritative chat catalog once for one dashboard render."""
        kwargs: dict[str, Any] = {}
        if self._catalog_timeout is not None:
            kwargs["timeout"] = self._catalog_timeout
        snapshot = discover_models(api_key_from_env(), capability=CAPABILITY_CHAT, **kwargs)
        return CatalogView(models=snapshot.models, source=snapshot.source, error=snapshot.error)

    def authentication(self) -> dict[str, Any]:
        """Describe the configured credential without revealing it."""
        key = api_key_from_env()
        return {
            "method": "api_key",
            "header": "Authorization: Bearer",
            "key_env": ORCAROUTER_API_KEY_ENV,
            "configured": bool(key),
            "masked_key": mask_api_key(key) if key else None,
            "key_management_url": f"{ORCAROUTER_AUTH_ORIGIN}/api/v1/auth/keys",
        }

    def models_payload(self, capability: str = CAPABILITY_CHAT) -> dict[str, Any]:
        """Return the selectable models for one capability, with their source."""
        if capability not in CATALOG_CAPABILITIES:
            raise ValueError(f"unsupported capability: {capability}")
        catalog = self.catalog()
        models = catalog.for_capability(capability)
        return {
            "provider": ORCAROUTER_NAME,
            "capability": capability,
            "capability_description": CAPABILITY_DESCRIPTIONS[capability],
            "catalog_url": ORCAROUTER_CHAT_CATALOG_URL,
            "source": catalog.source,
            "count": len(models),
            "error": catalog.error,
            "models": [model.as_dict() for model in models],
        }

    def provider_payload(self, capability: str = CAPABILITY_CHAT) -> dict[str, Any]:
        """Return everything the dashboard needs to render the provider panel."""
        if capability not in CATALOG_CAPABILITIES:
            raise ValueError(f"unsupported capability: {capability}")
        catalog = self.catalog()
        models = catalog.for_capability(capability)
        return {
            "provider": ORCAROUTER_NAME,
            "capability": capability,
            "capability_description": CAPABILITY_DESCRIPTIONS[capability],
            "home_url": ORCAROUTER_HOME_URL,
            "docs_url": ORCAROUTER_DOCS_URL,
            "auth_origin": ORCAROUTER_AUTH_ORIGIN,
            "api_base": ORCAROUTER_API_BASE,
            "catalog_url": ORCAROUTER_CHAT_CATALOG_URL,
            "source": catalog.source,
            "error": catalog.error,
            "authentication": self.authentication(),
            "catalog": {
                "model_count": len(catalog.models),
                "image_model_count": catalog.image_model_count,
            },
            "capabilities": [
                {
                    "name": name,
                    "description": CAPABILITY_DESCRIPTIONS[name],
                    "count": len(catalog.for_capability(name)),
                }
                for name in CATALOG_CAPABILITIES
            ],
            "count": len(models),
            "models": [model.as_dict() for model in models],
        }
