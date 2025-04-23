from __future__ import annotations

from typing import Dict, Any, List
from pydantic import BaseModel, Field
from redis import Redis


class SARIFBroadcastDetail(BaseModel):
    """Model for SARIF broadcast details, matches the model in types.py"""

    metadata: Dict[str, Any] = Field(
        ...,
        description="String to string map containing data that should be attached to outputs like log messages and OpenTelemetry trace attributes for traceability",
    )
    sarif: Dict[str, Any] = Field(..., description="SARIF Report compliant with provided schema")
    sarif_id: str
    task_id: str


class SARIFStore:
    """Store and retrieve SARIF objects in Redis"""

    def __init__(self, redis: Redis):
        """
        Initialize the SARIF store with a Redis connection.

        Args:
            redis: Redis connection
        """
        self.redis = redis
        self.key_prefix = "sarif:"

    def _get_key(self, task_id: str) -> str:
        """
        Get the Redis key for a task_id.

        Args:
            task_id: Task ID

        Returns:
            Redis key
        """
        return f"{self.key_prefix}{task_id.lower()}"

    def _decode_key(self, key) -> str:
        """
        Decode a Redis key if it's bytes, otherwise return as is.

        Args:
            key: Redis key, either bytes or string

        Returns:
            Decoded key as string
        """
        if isinstance(key, bytes):
            return key.decode("utf-8")
        return key

    def store(self, sarif_detail: SARIFBroadcastDetail) -> None:
        """
        Store a SARIF broadcast detail in Redis.

        Args:
            sarif_detail: The SARIF broadcast detail to store
        """
        task_id = sarif_detail.task_id
        key = self._get_key(task_id)

        # We'll use a Redis list to store multiple SARIF objects for the same task
        # Serialize the SARIF object to JSON
        sarif_json = sarif_detail.model_dump_json()

        # Add to the list for this task
        self.redis.rpush(key, sarif_json)

    def get_all(self) -> List[SARIFBroadcastDetail]:
        """
        Retrieve all SARIF objects from Redis.

        Returns:
            List of SARIF broadcast details
        """
        # Get all SARIF keys in Redis
        all_keys = self.redis.keys(f"{self.key_prefix}*")

        result = []
        for key in all_keys:
            # Decode the key if it's bytes
            decoded_key = self._decode_key(key)

            # Get all SARIF objects for this task
            sarif_list = self.redis.lrange(decoded_key, 0, -1)
            for sarif_json in sarif_list:
                # Parse each JSON string into a SARIFBroadcastDetail
                sarif_detail = SARIFBroadcastDetail.model_validate_json(sarif_json)
                result.append(sarif_detail)

        return result

    def get_by_task_id(self, task_id: str) -> List[SARIFBroadcastDetail]:
        """
        Retrieve all SARIF objects for a specific task.

        Args:
            task_id: Task ID

        Returns:
            List of SARIF broadcast details for this task
        """
        key = self._get_key(task_id)
        sarif_list = self.redis.lrange(key, 0, -1)

        result = []
        for sarif_json in sarif_list:
            sarif_detail = SARIFBroadcastDetail.model_validate_json(sarif_json)
            result.append(sarif_detail)

        return result

    def delete_by_task_id(self, task_id: str) -> int:
        """
        Remove all SARIF objects for a specific task.

        Args:
            task_id: Task ID

        Returns:
            Number of removed keys (0 or 1)
        """
        key = self._get_key(task_id)
        return self.redis.delete(key)
