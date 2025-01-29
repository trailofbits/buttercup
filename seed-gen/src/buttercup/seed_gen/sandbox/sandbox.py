import logging
import tempfile
from pathlib import Path

from buttercup.seed_gen.sandbox.execute_llm_code import wasm_run_script
from buttercup.seed_gen.utils import resolve_module_subpath

SEED_EXEC_RUNNER = resolve_module_subpath("sandbox/runner.py")

logger = logging.getLogger(__name__)


def sandbox_exec_funcs(functions: str) -> list[bytes]:
    """Run functions in wasm sandbox and return output of each"""
    povs = []
    with tempfile.TemporaryDirectory() as workdir_str:
        workdir = Path(workdir_str)
        function_path = workdir / "func.py"
        outdir = workdir / "output"
        function_path.write_text(functions)
        try:
            script_args = [function_path.name, outdir.name]
            wasm_run_script(workdir, SEED_EXEC_RUNNER, script_args)
            for pov_file in outdir.iterdir():
                povs.append(pov_file.read_bytes())
        except Exception as e:
            logger.error(f"Error running wasm sandbox {e}")
    return povs
