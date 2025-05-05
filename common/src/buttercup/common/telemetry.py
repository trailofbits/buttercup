import os
import logging
from enum import Enum

import openlit
from opentelemetry.trace import Span, Tracer, Status, StatusCode

logger = logging.getLogger(__name__)


class CRSActionCategory(Enum):
    """CRS Action Categories from AIxCC Telemetry Spec"""

    STATIC_ANALYSIS = "static_analysis"
    DYNAMIC_ANALYSIS = "dynamic_analysis"
    FUZZING = "fuzzing"
    PROGRAM_ANALYSIS = "program_analysis"
    BUILDING = "building"
    INPUT_GENERATION = "input_generation"
    PATCH_GENERATION = "patch_generation"
    TESTING = "testing"
    SCORING_SUBMISSION = "scoring_submission"


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

    logger.info("Sending telemetry to %s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    logger.info("Sending telemetry using %s", os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL"))

    openlit.init(application_name=application_name)


def set_crs_attributes(
    span: Span,
    crs_action_category: CRSActionCategory,
    crs_action_name: str,
    task_metadata: dict,
    extra_attributes: dict | None = None,
):
    extra_attributes = extra_attributes or {}
    span.set_attribute("crs.action.category", crs_action_category.value)
    span.set_attribute("crs.action.name", crs_action_name)

    for key, value in task_metadata.items():
        span.set_attribute(key, value)

    for key, value in extra_attributes.items():
        span.set_attribute(key, value)


def log_crs_action_ok(
    tracer: Tracer,
    crs_action_category: CRSActionCategory,
    crs_action_name: str,
    task_metadata: dict,
    extra_attributes: dict | None = None,
):
    extra_attributes = extra_attributes or {}
    with tracer.start_as_current_span(crs_action_name) as span:
        span.set_attribute("crs.action.category", crs_action_category.value)
        span.set_attribute("crs.action.name", crs_action_name)

        for key, value in task_metadata.items():
            span.set_attribute(key, value)

        for key, value in extra_attributes.items():
            span.set_attribute(key, value)

        span.set_status(Status(StatusCode.OK))
