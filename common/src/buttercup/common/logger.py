from opentelemetry._logs import set_logger_provider
import os

if os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL") == "grpc":
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
else:
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
import uuid
import logging
import tempfile

_is_initialized = False
PACKAGE_LOGGER_NAME = "buttercup"


def setup_package_logger(application_name: str, logger_name: str, log_level: str = "info") -> logging.Logger:
    global _is_initialized

    if not _is_initialized:
        # Clear any existing handlers to avoid duplicates
        root = logging.getLogger()
        if root.handlers:
            for handler in root.handlers:
                root.removeHandler(handler)

        # Create resource with service and environment information
        resource = Resource.create(
            attributes={
                "service.name": application_name,
                "service.instance.id": os.getenv("SERVICE_INSTANCE_ID", str(uuid.uuid4())),
            }
        )

        # Initialize the LoggerProvider with the created resource.
        logger_provider = LoggerProvider(resource=resource)

        # Configure the span exporter and processor based on whether the endpoint is effectively set.
        otlp_handler = None
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            set_logger_provider(logger_provider)
            exporter = OTLPLogExporter()

            # add the batch processors to the trace provider
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            otlp_handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)

        persistent_log_dir = os.getenv("PERSISTENT_LOG_DIR", None)

        handlers = [
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(tempfile.gettempdir(), f"{logger_name}.log")),
        ]
        if persistent_log_dir:
            if not os.path.exists(persistent_log_dir):
                os.makedirs(persistent_log_dir, exist_ok=True)

            handlers.append(logging.FileHandler(os.path.join(persistent_log_dir, f"{logger_name}.log")))

        if otlp_handler:
            handlers.append(otlp_handler)

        # Configure root logger
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

        _package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
        _package_logger.setLevel(log_level.upper())

        _is_initialized = True

    return logging.getLogger(PACKAGE_LOGGER_NAME)
