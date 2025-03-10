import logging
from buttercup.orchestrator.competition_api_client.configuration import Configuration
from buttercup.orchestrator.competition_api_client.api_client import ApiClient

logger = logging.getLogger(__name__)


def create_api_client(
    competition_api_url: str, competition_api_username: str, competition_api_password: str
) -> ApiClient:
    """Initialize the competition API client with common configuration.

    Args:
        competition_api_url: Base URL for the competition API

    Returns:
        ApiClient: Configured API client instance
    """
    configuration = Configuration(
        host=competition_api_url,
        username=competition_api_username,
        password=competition_api_password,
    )
    logger.info(f"Initializing API client with URL: {competition_api_url}")
    return ApiClient(configuration=configuration)
