import os
import logging
from enum import Enum
import uuid
from typing import Any

# Try to import OpenTelemetry, but don't fail if it's not available
try:
    import openlit
    import opentelemetry.attributes
    from opentelemetry import trace
    from opentelemetry.trace import Span, Tracer, Status, StatusCode
    from langchain_core.prompt_values import ChatPromptValue
    OPENTELEMETRY_AVAILABLE = True
    
    # Monkey patch the _clean_attribute function to handle ChatPromptValue
    _clean_attribute_orig = opentelemetry.attributes._clean_attribute
    
    def _clean_attribute_wrapper(key: str, value: Any, max_len: int | None = None) -> Any:
        """Wrapper around _clean_attribute to add custom behavior"""
        if isinstance(value, ChatPromptValue):
            value = value.to_string()
        return _clean_attribute_orig(key, value, max_len)
    
    opentelemetry.attributes._clean_attribute = _clean_attribute_wrapper
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    # Create dummy classes for when OpenTelemetry is not available
    class DummySpan:
        def set_attribute(self, key: str, value: Any) -> None:
            pass
        def set_status(self, status: Any) -> None:
            pass
    
    class DummyTracer:
        def start_as_current_span(self, name: str):
            from contextlib import contextmanager
            @contextmanager
            def dummy_context():
                yield DummySpan()
            return dummy_context()
    
    Span = DummySpan
    Tracer = DummyTracer
    Status = StatusCode = None


logger = logging.getLogger(__name__)
crs_instance_id = os.getenv("CRS_INSTANCE_ID", str(uuid.uuid4()))
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


def init_telemetry(application_name: str) -> None:
    """Initialize the telemetry for the application."""
    logger.info("Initializing telemetry for %s", application_name)
    
    if not OPENTELEMETRY_AVAILABLE:
        logger.info("OpenTelemetry module not installed, telemetry disabled")
        return
    
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set, telemetry disabled")
        return

    if not os.getenv("OTEL_EXPORTER_OTLP_HEADERS"):
        logger.warning("OTEL_EXPORTER_OTLP_HEADERS not set. This is required for authentication.")

    if not os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL"):
        logger.warning("OTEL_EXPORTER_OTLP_PROTOCOL not set")

    logger.info("Sending telemetry to %s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    logger.info("Sending telemetry using %s", os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL"))

    try:
        openlit.init(application_name=application_name)
        # Send a telemetry init trace
        tracer = trace.get_tracer(__name__)
        log_crs_action_ok(tracer, CRSActionCategory.TELEMETRY_INIT, application_name, {}, {})
    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        logger.info("Continuing without telemetry")


def set_crs_attributes(
    span: Span,
    crs_action_category: CRSActionCategory,
    crs_action_name: str,
    task_metadata: dict,
    extra_attributes: dict | None = None,
) -> None:
    if not OPENTELEMETRY_AVAILABLE:
        return
    
    extra_attributes = extra_attributes or {}
    try:
        span.set_attribute("crs.action.category", crs_action_category.value)
        span.set_attribute("crs.action.name", crs_action_name)
        span.set_attribute("service.instance.id", service_instance_id)
        span.set_attribute("crs.instance.id", crs_instance_id)

        for key, value in task_metadata.items():
            span.set_attribute(key, value)

        for key, value in extra_attributes.items():
            span.set_attribute(key, value)
    except Exception as e:
        logger.debug(f"Failed to set telemetry attributes: {e}")


def log_crs_action_ok(
    tracer: Tracer,
    crs_action_category: CRSActionCategory,
    crs_action_name: str,
    task_metadata: dict,
    extra_attributes: dict | None = None,
) -> None:
    if not OPENTELEMETRY_AVAILABLE:
        return
    
    extra_attributes = extra_attributes or {}
    try:
        with tracer.start_as_current_span(crs_action_name) as span:
            span.set_attribute("crs.action.category", crs_action_category.value)
            span.set_attribute("crs.action.name", crs_action_name)
            span.set_attribute("service.instance.id", service_instance_id)
            span.set_attribute("crs.instance.id", crs_instance_id)

            for key, value in task_metadata.items():
                span.set_attribute(key, value)

            for key, value in extra_attributes.items():
                span.set_attribute(key, value)

            if Status and StatusCode:
                span.set_status(Status(StatusCode.OK))
    except Exception as e:
        logger.debug(f"Failed to log telemetry action: {e}")
