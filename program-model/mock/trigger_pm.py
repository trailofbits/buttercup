import argparse
from redis import Redis
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.datastructures.msg_pb2 import IndexRequest


def main():
    prsr = argparse.ArgumentParser("trigger Program Model manually")
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--build_type", required=True)
    prsr.add_argument("--package_name", required=True)
    prsr.add_argument("--sanitizer", required=True)
    prsr.add_argument("--task_dir", required=True)
    prsr.add_argument("--task_id", required=True)
    args = prsr.parse_args()

    redis = Redis.from_url(args.redis_url)
    queue = QueueFactory(redis).create(QueueNames.INDEX)
    req = IndexRequest(
        build_type=args.build_type,
        package_name=args.package_name,
        sanitizer=args.sanitizer,
        task_dir=args.task_dir,
        task_id=args.task_id,
    )
    queue.push(req)


if __name__ == "__main__":
    main()
