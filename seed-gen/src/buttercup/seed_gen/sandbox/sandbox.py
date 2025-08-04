import logging
import shutil
import tempfile
from pathlib import Path

from buttercup.seed_gen.sandbox.execute_llm_code import wasm_run_script
from buttercup.seed_gen.utils import resolve_module_subpath

SEED_EXEC_RUNNER = resolve_module_subpath("sandbox/runner.py")

logger = logging.getLogger(__name__)


def sandbox_exec_funcs(functions: str, output_dir: Path):
    """Run functions in wasm sandbox and save seeds to output_dir"""
    with tempfile.TemporaryDirectory() as workdir_str:
        workdir = Path(workdir_str)
        function_path = workdir / "func.py"
        wasm_outdir = workdir / "output"
        function_path.write_text(functions)
        script_args = [function_path.name, wasm_outdir.name]
        wasm_run_script(workdir, SEED_EXEC_RUNNER, script_args)
        for pov_file in wasm_outdir.iterdir():
            if pov_file.is_file() and not pov_file.is_symlink():
                shutil.copy(pov_file, output_dir / pov_file.name)
