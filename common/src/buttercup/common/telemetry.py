import openlit
import os
import logging

logger = logging.getLogger(__name__)


def init_telemetry(application_name: str):
    """Initialize the telemetry for the application."""
    logger.info("Initializing telemetry for %s", application_name)
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        logger.error("OTEL_EXPORTER_OTLP_ENDPOINT not set, disabling telemetry")
        return

    if not os.getenv("OTEL_EXPORTER_OTLP_HEADERS"):
        logger.warning("OTEL_EXPORTER_OTLP_HEADERS not set. This is required for authentication.")

    if not os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL"):
        logger.warning("OTEL_EXPORTER_OTLP_PROTOCOL not set")

    openlit.init(application_name=application_name)
