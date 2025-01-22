import argparse
import uuid
import subprocess
from dataclasses import dataclass
from buttercup.common import oss_fuzz_tool
from buttercup.common.oss_fuzz_tool import OSSFuzzTool
from buttercup.program_model.indexer.entries_into_db import JanusStorage

import os
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
    wdir: str

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
        # TODO(Ian): do more forgiving error handling
        return emitted_image

    def index_target(self, idx_target: IndexTarget):
        emitted_image = self.build_image(idx_target)
        if emitted_image is None:
            return None
        
        indexuid = str(uuid.uuid4())
        output_dir = f"{self.conf.wdir}/output_{indexuid}"
        os.makedirs(output_dir, exist_ok=True)
        # TODO(Ian): we need to figure out how to make ccwrapper.sh not break LD detection
        command = ["docker", "run", "-v", f"{output_dir}:/kythe_out", "-e", "LD=ld", "-e", f"KYTHE_OUTPUT_DIRECTORY=/kythe_out", emitted_image, "compile"]
        # TODO(Ian): we probably shouldnt keep around indexing images for disk space reasons
        subprocess.run(command, check=True)
        return output_dir
    
@dataclass
class KytheConf:
    kythe_dir: str


class KytheTool:
    def __init__(self, conf: KytheConf):
        self.conf = conf

    def merge_kythe_output(self, input_dir: str, output_kzip: str):
        merge_path = os.path.join(self.conf.kythe_dir, "tools/kzip")

        total = []
        for fl in os.listdir(input_dir):
            if fl.endswith(".kzip"):
                total.append(os.path.join(input_dir, fl))

        command = [merge_path, "--output", output_kzip] + total
        subprocess.run(command, check=True)
        return True
    
    def cxx_index(self, input_kzip: str, output_kzip: str, output_bin: str):
        indexer_path = os.path.join(self.conf.kythe_dir, "indexers/cxx_indexer")
        command = [indexer_path, "-i", input_kzip, "-o", output_bin]
        subprocess.run(command, check=True)
        return True


def main():
    prsr = argparse.ArgumentParser("oss fuzz builder")
    prsr.add_argument("--scriptdir",required=True)
    prsr.add_argument("--url",required=True)
    prsr.add_argument("--python",default="python")
    prsr.add_argument("--allow_pull", default=False)
    prsr.add_argument("--base_image_url",required=True)
    prsr.add_argument("--oss_fuzz_dir",required=True)
    prsr.add_argument("--package_name",required=True)
    prsr.add_argument("--wdir",required=True)
    prsr.add_argument("--kythe_dir",required=True)
    args = prsr.parse_args()

    conf = Conf(args.scriptdir, args.url, args.python, args.allow_pull, args.base_image_url, args.wdir)
    indexer = Indexer(conf)
    output_dir = indexer.index_target(IndexTarget(args.oss_fuzz_dir, args.package_name))
    print(output_dir)
    output_id = str(uuid.uuid4())
    ktool = KytheTool(args.kythe_dir)
    merged_kzip = os.path.join(args.wdir, f"kythe_output_merge_{output_id}.kzip")
    ktool.merge_kythe_output(output_dir, merged_kzip)
    cxx_bin = os.path.join(args.wdir, f"kythe_output_cxx_{output_id}.bin")
    ktool.cxx_index(merged_kzip, cxx_bin)

    with open(cxx_bin, "rb") as f:
        JanusStorage(args.url).process_stream(args.package_name, f)

if __name__ == "__main__":
    main()