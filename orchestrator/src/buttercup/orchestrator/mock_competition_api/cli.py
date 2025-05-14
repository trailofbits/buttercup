#!/usr/bin/env python3
"""
Command-line interface for the mock competition API server.
"""

import argparse
import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run the mock competition API server")
    parser.add_argument(
        "--tarball",
        required=False,
        help="Path to the tarball containing files to serve (optional, can be uploaded via HTTP later)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind the server to")

    # CRS integration options
    parser.add_argument("--crs-url", default="http://localhost:8000/v1/task/", help="CRS task server URL")
    parser.add_argument("--crs-key-id", default="", help="CRS API key ID for authentication")
    parser.add_argument("--crs-token", default="", help="CRS API token for authentication")
    parser.add_argument("--crs-enabled", action="store_true", help="Enable sending tasks to CRS")

    # Add base URL parameter for file URLs
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="Base URL for the mock API (used in file URLs sent to CRS, e.g., http://mock-api.example.com)",
    )

    args = parser.parse_args()

    # Verify the tarball exists if provided
    tarball_path = None
    if args.tarball:
        tarball_path = Path(args.tarball)
        if not tarball_path.exists():
            logger.error(f"Tarball not found: {tarball_path}")
            sys.exit(1)

    # Import and run the mock API
    try:
        from buttercup.orchestrator.mock_competition_api import MockCompetitionAPI, CRSConfig

        logger.info(f"Starting mock competition API server on {args.host}:{args.port}")
        if tarball_path:
            logger.info(f"Using initial tarball: {tarball_path}")
        else:
            logger.info(
                "No initial tarball provided. You can upload one via HTTP at http://<host>:<port>/upload-tarball/"
            )

        # Create CRS config
        crs_config = CRSConfig(
            task_server_url=args.crs_url,
            api_key_id=args.crs_key_id,
            api_token=args.crs_token,
            enabled=args.crs_enabled,
            base_url=args.base_url,
        )

        # Log CRS configuration
        if args.crs_enabled:
            logger.info(f"CRS integration ENABLED - Will send tasks to {args.crs_url}")
            logger.info(f"Files will be served from base URL: {args.base_url}")
        else:
            logger.info("CRS integration DISABLED - Will only log tasks (use --crs-enabled to send to CRS)")

        api = MockCompetitionAPI(str(tarball_path) if tarball_path else None, crs_config)

        # Print usage information
        logger.info("\nAPI Usage:")
        logger.info("1. Upload a tarball (if not provided at startup):")
        logger.info(
            f"   curl -X POST 'http://{args.host}:{args.port}/upload-tarball/' -F 'file=@/path/to/your/files.tar.gz'"
        )
        logger.info("2. Upload the control file:")
        logger.info(
            f"   curl -X POST 'http://{args.host}:{args.port}/control-file/' -F 'file=@/path/to/control_file.json'"
        )
        logger.info("3. Check file status:")
        logger.info(f"   curl 'http://{args.host}:{args.port}/files-status/'")
        logger.info("\nThe server is now running and will accept control file and tarball uploads.")

        api.run(host=args.host, port=args.port)
    except ImportError as e:
        logger.error(f"Failed to import mock competition API: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error running mock competition API: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
