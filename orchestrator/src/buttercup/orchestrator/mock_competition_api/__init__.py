"""
Mock Competition API package.

This package provides a mock implementation of the competition API for testing purposes.
"""

from .api import MockCompetitionAPI, CRSConfig

# Export these names when using "from buttercup.orchestrator.mock_competition_api import *"
__all__ = ["MockCompetitionAPI", "CRSConfig"]
