"""CLI for the program-model REST API server."""

import argparse
import logging
import uvicorn

logger = logging.getLogger(__name__)


def main() -> None:
    """Main CLI entry point for the program-model API server."""
    parser = argparse.ArgumentParser(
        description="Buttercup Program Model REST API Server"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level (default: info)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting Buttercup Program Model API Server")
    logger.info(f"Host: {args.host}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Log level: {args.log_level}")

    # Start the server
    uvicorn.run(
        "buttercup.program_model.api.server:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
