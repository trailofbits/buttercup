import logging
import shutil
import tempfile
from pathlib import Path

from buttercup.seed_gen.sandbox.execute_llm_code import wasm_run_script
from buttercup.seed_gen.utils import resolve_module_subpath

SEED_EXEC_RUNNER = resolve_module_subpath("sandbox/runner.py")

logger = logging.getLogger(__name__)


def sandbox_exec_funcs(functions: str, output_dir: Path) -> None:
    """Run functions in wasm sandbox and save seeds to output_dir"""
    logger.debug("sandbox_exec_funcs called with output_dir: %s", output_dir)
    logger.debug("output_dir exists: %s", output_dir.exists())
    with tempfile.TemporaryDirectory() as workdir_str:
        workdir = Path(workdir_str)
        function_path = workdir / "func.py"
        wasm_outdir = workdir / "output"
        function_path.write_text(functions)
        logger.debug("About to run wasm_run_script with workdir=%s, runner=%s", workdir, SEED_EXEC_RUNNER)
        script_args = [function_path.name, wasm_outdir.name]
        wasm_run_script(workdir, SEED_EXEC_RUNNER, script_args)
        logger.debug("wasm_run_script completed")
        logger.debug("wasm_outdir: %s", wasm_outdir)
        logger.debug("wasm_outdir exists: %s", wasm_outdir.exists())
        if wasm_outdir.exists():
            files_in_wasm = list(wasm_outdir.iterdir())
            logger.debug("Files in wasm_outdir (%d): %s", len(files_in_wasm), [f.name for f in files_in_wasm])
        else:
            logger.warning("wasm_outdir does not exist!")

        copied_count = 0
        for pov_file in wasm_outdir.iterdir():
            if pov_file.is_file() and not pov_file.is_symlink():
                target_path = output_dir / pov_file.name
                logger.debug("Copying %s to %s", pov_file, target_path)
                shutil.copy(pov_file, target_path)
                copied_count += 1
        logger.debug("Copied %d files to output_dir", copied_count)
        if output_dir.exists():
            files_in_output = list(output_dir.iterdir())
            logger.debug(
                "Files in output_dir after copy (%d): %s", len(files_in_output), [f.name for f in files_in_output]
            )
