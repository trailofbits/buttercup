"""Run seed generation functions

Should run in a WASI environment for sandboxing
"""

import importlib.util
import inspect
import logging
import platform
import sys
from pathlib import Path
from types import ModuleType


def load_module_from_path(path: Path) -> ModuleType | None:
    """Load python module"""
    spec = importlib.util.spec_from_file_location("func_module", path)
    module = None
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def exec_seed_funcs(seed_func_path: Path, output_dir: Path) -> None:
    """Execute seed functions in file and save seeds"""
    module = load_module_from_path(seed_func_path)
    if module is None:
        logging.error("Failed to load module")
        return
    for func_name, func in inspect.getmembers(module, inspect.isfunction):
        try:
            logging.info(f"Executing function: {func_name}")
            seed = func()
            filename = f"{func_name}.seed"
            path = output_dir / filename
            with open(path, "wb") as f:
                f.write(seed)
        except Exception as e:
            logging.error(f"Error occurred: {e}")


def main() -> None:
    """Execute LLM seed functions"""
    assert platform.system() == "wasi"  # check the script is sandboxed
    seed_func_str = sys.argv[1].strip()  # file with seed functions
    output_dir_str = sys.argv[2].strip()  # output directory to store seeds
    output_dir = Path(output_dir_str)
    seed_func_path = Path(seed_func_str)
    output_dir.mkdir()
    exec_seed_funcs(seed_func_path, output_dir)


if __name__ == "__main__":
    main()
