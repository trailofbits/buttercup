from enum import Enum
from buttercup.common.llm import create_default_llm


class Task(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


def do_seed_init() -> list[bytes]:
    """Do seed-init task"""
    llm = create_default_llm()
    msg = llm.invoke("Hello, world!")
    return [msg.content.encode("utf-8")]


def do_seed_explore() -> list[bytes]:
    """Do seed-explore task"""
    raise NotImplementedError(f"{Task.SEED_EXPLORE} not implemented")


def do_vuln_discovery() -> list[bytes]:
    """Do vuln-discovery task"""
    raise NotImplementedError(f"{Task.VULN_DISCOVERY} not implemented")
