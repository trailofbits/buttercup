import argparse
from buttercup.common.queues import BuildConfiguration
from buttercup.common.oss_fuzz_tool import OSSFuzzTool, Conf
# General idea for fuzzer arch:
# build out a build and a run entrypoint, fuzzer is checkpointed as a configuration after a build
# build is in shared mount for all fuzzer pods.
# fuzzer pod is dispatched to run and uses a clusterfuzz engine from runner base and our own python entrypoint to run how we
# want and communicate.

# build might be possible with just helper.py but may want to share with clusterfuzz to make engine options line up


def main():
    prsr = argparse.ArgumentParser("Fuzzing Infra")
    prsr.add_argument("target")
    prsr.add_argument("--ossfuzz", required=True)
    prsr.add_argument("--python", default="python")
    args = prsr.parse_args()

    tool = OSSFuzzTool(Conf(args.ossfuzz, args.python))
    tool.build_fuzzer_with_cache(BuildConfiguration(args.target, None, None))


if __name__ == "__main__":
    main()
