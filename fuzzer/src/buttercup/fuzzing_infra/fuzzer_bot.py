import argparse
import distutils.dir_util
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import time
import os 
from buttercup.common.datastructures.fuzzer_msg_pb2 import WeightedTarget
from buttercup.common.queues import TARGET_LIST_NAME, NormalQueue, SerializationDeserializationQueue
from buttercup.common.constants import CORPUS_DIR_NAME
from buttercup.common import constants
from buttercup.common import utils
from redis import Redis
import random
import tempfile
import shutil
import distutils
import os



def main():
    prsr = argparse.ArgumentParser("fuzz bot")
    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--wdir", required=True)

    args = prsr.parse_args()

    os.makedirs(args.wdir, exist_ok=True)


    runner = Runner(Conf(args.timeout))
    seconds_sleep = args.timer // 1000
    conn = Redis.from_url(args.redis_url)
    q = SerializationDeserializationQueue(NormalQueue(TARGET_LIST_NAME, conn), WeightedTarget)
    while True:
        
        weighted_items: list[WeightedTarget] = list(iter(q))
            
        if len(weighted_items) > 0:
            #td = tempfile.mkdtemp()
            #if True:
            with tempfile.TemporaryDirectory(prefix=args.wdir) as td:
                print(type(weighted_items[0]))
                chc = random.choices([it for it in weighted_items],weights=[it.weight for it in weighted_items],k=1)[0]
                build_dir = os.path.dirname(chc.harness_path)
                corpdir = os.path.join(build_dir, CORPUS_DIR_NAME)
                os.makedirs(corpdir, exist_ok=True)
                utils.copyanything(build_dir, os.path.join(td, os.path.basename(build_dir)))
                copied_build_dir = os.path.join(td, os.path.basename(build_dir))
                copied_corp_dir = os.path.join(copied_build_dir, CORPUS_DIR_NAME)
                tgtbuild = chc.target
                fuzz_conf = FuzzConfiguration(copied_corp_dir, os.path.join(copied_build_dir, os.path.basename(chc.harness_path)), tgtbuild.engine, tgtbuild.sanitizer)
                runner.run_fuzzer(fuzz_conf)
                distutils.dir_util.copy_tree(copied_corp_dir, corpdir)
        time.sleep(seconds_sleep)

if __name__ == "__main__":
    main()