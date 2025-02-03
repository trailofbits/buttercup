from typing import Iterator
from redis import Redis


class RedisSet:
    def __init__(self, redis: Redis, set_name: str):
        self.redis = redis
        self.set_name = set_name

    # Returns True if the value was already in the set
    def add(self, value: str) -> bool:
        return self.redis.sadd(self.set_name, value) == 0

    # Returns True if the value was already in the set
    def remove(self, value: str) -> bool:
        return self.redis.srem(self.set_name, value) == 1

    def contains(self, value: str) -> bool:
        return self.redis.sismember(self.set_name, value)

    def __iter__(self) -> Iterator[str]:
        for member in self.redis.smembers(self.set_name):
            yield member.decode("utf-8")

    def __len__(self) -> int:
        return self.redis.scard(self.set_name)
