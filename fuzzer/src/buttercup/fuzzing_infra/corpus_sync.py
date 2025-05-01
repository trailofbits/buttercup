from buttercup.common.corpus import Corpus
from buttercup.common.logger import setup_package_logger
from redis import Redis
import logging
import argparse
import time
from buttercup.common.sets import MergedCorpusSetLock, FailedToAcquireLock
from buttercup.common.sets import MERGING_LOCK_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wdir", type=str, required=True)
    parser.add_argument("--sync-interval", type=int, default=120)
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--redis-url", type=str, required=True)
    args = parser.parse_args()

    setup_package_logger(__name__, args.log_level)
    last_sync = 0
    logger.info(f"Syncing corpora from {args.wdir}")
    redis = Redis.from_url(args.redis_url)
    while True:
        if time.time() - last_sync > args.sync_interval:
            last_sync = time.time()
            try:
                corpus_list = Corpus.locally_available(args.wdir)
                logger.info(f"Found {len(corpus_list)} corpora")

                for corpus in corpus_list:
                    # critical section we cant allow for a worker to upload while the merger is running
                    try:
                        with MergedCorpusSetLock(
                            redis, corpus.task_id, corpus.harness_name, MERGING_LOCK_TIMEOUT_SECONDS
                        ).acquire():
                            corpus.remove_any_merged(redis)
                            logger.info(f"Syncing corpus {corpus.path} to remote")
                            corpus.sync_to_remote()
                    except FailedToAcquireLock:
                        logger.info(f"Skipping upload for {corpus.path} because another worker has the lock")
                    logger.info(f"Syncing corpus {corpus.path} from remote")
                    corpus.sync_from_remote()
                    logger.info(f"Syncing corpus {corpus.path} Done")
            except Exception as e:
                logger.error(f"Error syncing corpora: {e}")

        print(".")
        time.sleep(10)


if __name__ == "__main__":
    main()
