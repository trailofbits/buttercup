import argparse
from redis import Redis
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.datastructures.msg_pb2 import BuildRequest


def main():
    prsr = argparse.ArgumentParser("stimulate build bot manually")
    prsr.add_argument("--target_package", required=True)
    prsr.add_argument("--ossfuzz", required=True)
    prsr.add_argument("--engine", required=True)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--sanitizer", required=True)
    prsr.add_argument("--source_path", required=True)
    prsr.add_argument("--task_id", required=True)
    args = prsr.parse_args()

    redis = Redis.from_url(args.redis_url)
    queue = QueueFactory(redis).create(QueueNames.BUILD)
    req = BuildRequest(
        package_name=args.target_package,
        engine=args.engine,
        sanitizer=args.sanitizer,
        ossfuzz=args.ossfuzz,
        source_path=args.source_path,
        task_id=args.task_id,
    )
    queue.push(req)


if __name__ == "__main__":
    main()
