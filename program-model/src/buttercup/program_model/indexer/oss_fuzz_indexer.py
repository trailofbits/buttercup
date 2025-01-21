import argparse
import uuid
import subprocess
from dataclasses import dataclass
from buttercup.common import oss_fuzz_tool
from buttercup.common.oss_fuzz_tool import OSSFuzzTool

@dataclass
class IndexTarget:
    oss_fuzz_dir: str
    package_name: str

@dataclass
class Conf:
    scriptdir: str
    url: str
    python: str
    allow_pull: bool
    base_image_url: str


class Indexer:
    def __init__(self, conf: Conf):
        self.conf = conf


    def build_image(self, idx_target: IndexTarget):
        fzz_tool = OSSFuzzTool(oss_fuzz_tool.Conf(idx_target.oss_fuzz_dir, self.conf.python, self.conf.allow_pull, self.conf.base_image_url))
        base_image_name = fzz_tool.build_base_image(idx_target.package_name)
        print(base_image_name)
        if base_image_name is None:
            return None
        
        buildid = str(uuid.uuid4())
        emitted_image = f"kyther_indexer_image_{idx_target.package_name}_{buildid}"
        wdir = f"{self.conf.scriptdir}"
        command = ["docker", "build" , "-t", emitted_image, "--build-arg", f"BASE_IMAGE={base_image_name}", "."]
        subprocess.run(command, check=True, cwd=wdir)

def main():
    prsr = argparse.ArgumentParser("oss fuzz builder")
    prsr.add_argument("--scriptdir",required=True)
    prsr.add_argument("--url",required=True)
    prsr.add_argument("--python",default="python")
    prsr.add_argument("--allow_pull", default=False)
    prsr.add_argument("--base_image_url",required=True)
    prsr.add_argument("--oss_fuzz_dir",required=True)
    prsr.add_argument("--package_name",required=True)
    args = prsr.parse_args()

    conf = Conf(args.scriptdir, args.url, args.python, args.allow_pull, args.base_image_url)
    indexer = Indexer(conf)
    indexer.build_image(IndexTarget(args.oss_fuzz_dir, args.package_name))

if __name__ == "__main__":
    main()