from buttercup.common.corpus import Corpus
from buttercup.common.logger import setup_package_logger
import logging
import argparse
import time

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wdir", type=str, required=True)
    parser.add_argument("--sync-interval", type=int, default=120)
    parser.add_argument("--log-level", type=str, default="INFO")
    args = parser.parse_args()

    setup_package_logger(__name__, args.log_level)
    last_sync = 0
    logger.info(f"Syncing corpora from {args.wdir}")

    while True:
        if time.time() - last_sync > args.sync_interval:
            last_sync = time.time()
            try:
                corpus_list = Corpus.locally_available(args.wdir)
                logger.info(f"Found {len(corpus_list)} corpora")
                for corpus in corpus_list:
                    logger.info(f"Syncing corpus {corpus.path} to remote")
                    corpus.sync_to_remote()
                    logger.info(f"Syncing corpus {corpus.path} from remote")
                    corpus.sync_from_remote()
                    logger.info(f"Syncing corpus {corpus.path} Done")
            except Exception as e:
                logger.error(f"Error syncing corpora: {e}")

        print(".")
        time.sleep(10)


if __name__ == "__main__":
    main()
