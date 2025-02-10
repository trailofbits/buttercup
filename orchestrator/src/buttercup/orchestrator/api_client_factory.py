import logging
from buttercup.orchestrator.competition_api_client.configuration import Configuration
from buttercup.orchestrator.competition_api_client.api_client import ApiClient

logger = logging.getLogger(__name__)

def create_api_client(competition_api_url: str) -> ApiClient:
    """Initialize the competition API client with common configuration.
    
    Args:
        competition_api_url: Base URL for the competition API
        
    Returns:
        ApiClient: Configured API client instance
    """
    configuration = Configuration(
        host=competition_api_url,
        username="api_key_id",  # TODO: Make configurable
        password="api_key_token",  # TODO: Make configurable
    )
    logger.info(f"Initializing API client with URL: {competition_api_url}")
    return ApiClient(configuration=configuration) 