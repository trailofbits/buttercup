"""Execute LLM-generated functions in WASM sandbox

Reference:
https://til.simonwillison.net/webassembly/python-in-a-wasm-sandbox
https://github.com/bytecodealliance/componentize-py/blob/c6c8447db66f5de66671a6b57ad47c61cb094af8/examples/sandbox/host.py
"""

import argparse
import logging
import os
import shutil
from pathlib import Path

from wasmtime import Config, Engine, Linker, Module, Store, WasiConfig

# Download: https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm
PYTHON_WASM_BUILD_PATH = os.environ["PYTHON_WASM_BUILD_PATH"]

MEMORY_LIMIT_BYTES = 50 * 1024 * 1024


def wasm_run_script(root_dir: Path, script_path: Path, script_args: list[str]) -> None:
    """Run python script in WASM in root dir"""
    # setup up wasmtime
    engine_config = Config()
    engine_config.consume_fuel = False
    engine_config.cache = True
    engine = Engine(engine_config)
    linker = Linker(engine)
    linker.define_wasi()
    python_module = Module.from_file(linker.engine, PYTHON_WASM_BUILD_PATH)
    shutil.copy(script_path, root_dir)
    script_root_path = Path("/") / script_path.name
    config = WasiConfig()
    config.argv = ("python", str(script_root_path)) + tuple(script_args)
    config.preopen_dir(str(root_dir), "/")  # mount root dir for Wasm
    out_log = root_dir / "stdout.log"
    err_log = root_dir / "stderr.log"
    config.stdout_file = out_log
    config.stderr_file = err_log
    store = Store(linker.engine)
    store.set_limits(memory_size=MEMORY_LIMIT_BYTES)
    store.set_wasi(config)
    instance = linker.instantiate(store, python_module)
    start = instance.exports(store)["_start"]
    try:
        start(store)  # type: ignore[operator]
    except Exception as e:
        logging.error(e)
        raise e


def main() -> None:
    """Execute LLM seed functions"""
    parser = argparse.ArgumentParser()
    parser.add_argument("root_dir", type=Path, help="R/W Root dir to mount for Wasm")
    parser.add_argument("script", type=Path, help="Script to execute in Wasm")
    parser.add_argument("script_args", type=str, nargs="*", help="Args passed to the script")
    args = parser.parse_args()
    root_dir: Path = args.root_dir
    script: Path = args.script
    script_args: list[str] = args.script_args
    if not root_dir.is_dir():
        logging.error("Root directory doesn't exist: %s", root_dir)
        return
    if not script.is_file():
        logging.error("Script isn't a file: %s", script)
        return
    wasm_run_script(root_dir, script, script_args)


if __name__ == "__main__":
    main()
