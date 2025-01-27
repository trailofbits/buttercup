import pytest
from redis import Redis
from buttercup.common.maps import Map

@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=0)

