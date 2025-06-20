import os
import logging
from enum import Enum
import uuid

import openlit
import opentelemetry.attributes
from opentelemetry import trace
from opentelemetry.trace import Span, Tracer, Status, StatusCode
from langchain_core.prompt_values import ChatPromptValue

# Monkey patch the _clean_attribute function to handle ChatPromptValue
_clean_attribute_orig = opentelemetry.attributes._clean_attribute


def _clean_attribute_wrapper(key: str, value, max_len=None):
    """Wrapper around _clean_attribute to add custom behavior"""
    if isinstance(value, ChatPromptValue):
        value = value.to_string()

    return _clean_attribute_orig(key, value, max_len)


opentelemetry.attributes._clean_attribute = _clean_attribute_wrapper


logger = logging.getLogger(__name__)
# NOTE: we made the mistake of using SERVICE_INSTANCE_ID as CRS_INSTANCE_ID, so we're keeping it for now
crs_instance_id = os.getenv("SERVICE_INSTANCE_ID", str(uuid.uuid4()))
service_instance_id = str(uuid.uuid4())


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
    TELEMETRY_INIT = "telemetry_init"


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

    # Send a telemetry init trace
    tracer = trace.get_tracer(__name__)
    log_crs_action_ok(tracer, CRSActionCategory.TELEMETRY_INIT, application_name, {}, {})


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
    span.set_attribute("service.instance.id", service_instance_id)
    span.set_attribute("crs.instance.id", crs_instance_id)

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
        span.set_attribute("service.instance.id", service_instance_id)
        span.set_attribute("crs.instance.id", crs_instance_id)

        for key, value in task_metadata.items():
            span.set_attribute(key, value)

        for key, value in extra_attributes.items():
            span.set_attribute(key, value)

        span.set_status(Status(StatusCode.OK))
