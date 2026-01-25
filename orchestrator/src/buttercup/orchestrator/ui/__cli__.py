import logging

import uvicorn

from buttercup.common.logger import setup_package_logger
from buttercup.common.telemetry import init_telemetry
from buttercup.orchestrator.ui.config import Settings

# Import the generated FastAPI app

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()  # type: ignore[missing-argument]
    setup_package_logger("ui", __name__, settings.log_level)
    init_telemetry("ui")
    logger.info(f"Starting UI with settings: {settings}")

    # Start the FastAPI app with uvicorn
    uvicorn.run(
        "buttercup.orchestrator.ui.competition_api.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()
