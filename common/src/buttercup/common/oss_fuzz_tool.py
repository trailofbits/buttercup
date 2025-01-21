from dataclasses import dataclass
from buttercup.common.queues import BuildConfiguration
import subprocess
import os 
from typing import Optional

@dataclass
class Conf:
    oss_fuzz_path: str
    python_path: str
    allow_pull: bool
    base_image_url: str

class OSSFuzzTool:
    def __init__(self, conf: Conf):
        self._conf = conf
        self._helper_path = os.path.join(self._conf.oss_fuzz_path, "infra/helper.py")

    @staticmethod
    def add_optional_arg(lst: list, flag: str, arg: str):
        if arg is not None:
            lst.append(flag)
            lst.append(arg)

    def build_fuzzer_command(self, cmd:str , fuzz_conf: BuildConfiguration):
        args = [self._conf.python_path, self._helper_path, cmd]

        OSSFuzzTool.add_optional_arg(args, "--engine", fuzz_conf.engine)
        OSSFuzzTool.add_optional_arg(args, "--sanitizer", fuzz_conf.sanitizer)
        args.append(fuzz_conf.project_id)
        return args

    def check_fuzzer_runs(self, fuzz_conf: BuildConfiguration):
        args = self.build_fuzzer_command("check_build", fuzz_conf)
        ret = subprocess.run(args)
        return ret.returncode == 0


    def build_base_image(self, package_conf: str) -> Optional[str]: 
        args = [self._conf.python_path, self._helper_path, "build_image"]

        if self._conf.allow_pull:
            args.append("--pull")
        else: 
            args.append("--no-pull")

        args.append(package_conf)
        ret = subprocess.run(args)
        if ret.returncode == 0:
            return f"{self._conf.base_image_url}/{package_conf}"
        else: 
            return None
        

    def build_fuzzer(self, fuzz_conf: BuildConfiguration):
        args = self.build_fuzzer_command("build_fuzzers", fuzz_conf)
        ret = subprocess.run(args)
        return ret.returncode == 0

    def build_fuzzer_with_cache(self, fuzz_conf: BuildConfiguration):
        if not self.check_fuzzer_runs(fuzz_conf):
            return self.build_fuzzer(fuzz_conf)

        return True