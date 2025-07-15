"""Queue adapter for bridging Redis queues with Python queues."""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from buttercup.common.queues import ReliableQueue

logger = logging.getLogger(__name__)


@dataclass
class RedisQueueItem:
    """Wrapper for items from Redis queues."""
    
    item: Any  # The actual RQItem from Redis
    source_queue: ReliableQueue  # The queue it came from
    
    @property
    def deserialized(self):
        """Get the deserialized message."""
        return self.item.deserialized
    
    @property
    def item_id(self):
        """Get the item ID."""
        return self.item.item_id
    
    def ack(self):
        """Acknowledge the item in the source queue."""
        self.source_queue.ack_item(self.item_id)
    
    def times_delivered(self) -> int:
        """Get the number of times this item has been delivered."""
        return self.source_queue.times_delivered(self.item_id)