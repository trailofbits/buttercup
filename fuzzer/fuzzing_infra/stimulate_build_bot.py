import argparse
from redis import Redis
from common.queues import BUILD_QUEUE_NAME, ReliableQueue, BUILDER_BOT_GROUP_NAME
from common.datastructures.fuzzer_msg_pb2 import BuildRequest


def main():
    prsr = argparse.ArgumentParser("stimulate build bot manually")
    prsr.add_argument("--target_package", required=True)
    prsr.add_argument("--ossfuzz", required=True)
    prsr.add_argument("--engine", required=True)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--sanitizer", required=True)
    args = prsr.parse_args()

    redis = Redis.from_url(args.redis_url)
    queue = ReliableQueue(BUILD_QUEUE_NAME,BUILDER_BOT_GROUP_NAME,redis, 108000, BuildRequest)
    req = BuildRequest(package_name=args.target_package, engine=args.engine, sanitizer=args.sanitizer, ossfuzz=args.ossfuzz)
    queue.push(req)

if __name__ == "__main__":
    main()