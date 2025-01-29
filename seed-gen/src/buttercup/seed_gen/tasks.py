from enum import Enum

# from buttercup.common.llm import create_default_llm
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs


class Task(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


def do_seed_init() -> list[bytes]:
    """Do seed-init task"""
    # llm = create_default_llm()
    # msg = llm.invoke("Hello, world!")
    test_function = "def gen_test() -> bytes: return b'test'"
    outputs = sandbox_exec_funcs(test_function)
    # return [msg.content.encode("utf-8")]
    return outputs


def do_seed_explore() -> list[bytes]:
    """Do seed-explore task"""
    raise NotImplementedError(f"{Task.SEED_EXPLORE} not implemented")


def do_vuln_discovery() -> list[bytes]:
    """Do vuln-discovery task"""
    raise NotImplementedError(f"{Task.VULN_DISCOVERY} not implemented")
