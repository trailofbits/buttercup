import argparse
from dataclasses import dataclass

@dataclass
class IndexTarget:
    oss_fuzz_dir: str
    package_name: str

@dataclass
class Conf:
    scriptdir: str
    url: str


class Indexer:
    def __init__(self, conf: Conf):
        self.conf = conf


    def build_image(self):
        command = ["docker build "]

def main():
    prsr = argparse.ArgumentParser("oss fuzz builder")
    prsr.add_argument("--scriptdir")
    prsr.add_argument("--url")

    args = prsr.parse_args()

    conf = Conf(args.scriptdir, args.url)

if __name__ == "__main__":
    main()