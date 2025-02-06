import argparse
import logging
import os
from buttercup.common.logger import setup_package_logger

logger = logging.getLogger(__name__)


def main():
    prsr = argparse.ArgumentParser("fuzz bot")
    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--wdir", required=True)

    args = prsr.parse_args()
    setup_package_logger(__name__, "DEBUG")

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {args.wdir})")

    raise NotImplementedError


if __name__ == "__main__":
    main()
