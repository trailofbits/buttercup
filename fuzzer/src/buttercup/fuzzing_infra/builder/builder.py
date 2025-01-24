import argparse
import subprocess
import os
from dataclasses import dataclass
from buttercup.common.queues import BuildConfiguration
# General idea for fuzzer arch:
# build out a build and a run entrypoint, fuzzer is checkpointed as a configuration after a build
# build is in shared mount for all fuzzer pods.
# fuzzer pod is dispatched to run and uses a clusterfuzz engine from runner base and our own python entrypoint to run how we
# want and communicate.

# build might be possible with just helper.py but may want to share with clusterfuzz to make engine options line up


@dataclass
class Conf:
    oss_fuzz_path: str
    python_path: str


class OSSFuzzTool:
    def __init__(self, conf: Conf):
        self._conf = conf
        self._helper_path = os.path.join(self._conf.oss_fuzz_path, "infra/helper.py")

    @staticmethod
    def add_optional_arg(lst: list, flag: str, arg: str):
        if arg is not None:
            lst.append(flag)
            lst.append(arg)

    def build_fuzzer_command(self, cmd: str, fuzz_conf: BuildConfiguration):
        args = [self._conf.python_path, self._helper_path, cmd]

        OSSFuzzTool.add_optional_arg(args, "--engine", fuzz_conf.engine)
        OSSFuzzTool.add_optional_arg(args, "--sanitizer", fuzz_conf.sanitizer)
        args.append(fuzz_conf.project_id)
        return args

    def check_fuzzer_runs(self, fuzz_conf: BuildConfiguration):
        args = self.build_fuzzer_command("check_build", fuzz_conf)
        ret = subprocess.run(args)
        return ret.returncode == 0

    def build_fuzzer(self, fuzz_conf: BuildConfiguration):
        args = self.build_fuzzer_command("build_fuzzers", fuzz_conf)
        ret = subprocess.run(args)
        return ret.returncode == 0

    def build_fuzzer_with_cache(self, fuzz_conf: BuildConfiguration):
        if not self.check_fuzzer_runs(fuzz_conf):
            return self.build_fuzzer(fuzz_conf)

        return True


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
