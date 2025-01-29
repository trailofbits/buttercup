import os
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

from buttercup.seed_gen.sandbox.runner import exec_seed_funcs, load_module_from_path


def create_seed1() -> bytes:
    return b"seed1"


def create_seed2() -> bytes:
    return b"seed2"


@patch("buttercup.seed_gen.sandbox.runner.load_module_from_path")
def test_exec_seed_funcs(mocked_load_module):
    seed_module = types.ModuleType("func_module")
    seed_module.create_seed1 = create_seed1
    seed_module.create_seed2 = create_seed2
    mocked_load_module.return_value = seed_module
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir_path = Path(str(tempdir))
        dummy_path = Path("dummy")
        exec_seed_funcs(dummy_path, tempdir_path)
        seed_file1 = tempdir_path / "create_seed1.seed"
        seed_file2 = tempdir_path / "create_seed2.seed"
        seed_files = [file for file in tempdir_path.iterdir()]
        assert len(seed_files) == 2
        assert seed_file1.exists()
        assert seed_file2.exists()
        assert seed_file1.read_bytes() == b"seed1"
        assert seed_file2.read_bytes() == b"seed2"


def test_load_module_from_path():
    file_path = os.path.abspath(__file__)
    module_path = Path(file_path).parent / "data/example_seed_funcs.py"
    module = load_module_from_path(module_path)
    assert hasattr(module, "gen_test_case_short_cookie")
    assert hasattr(module, "gen_test_case_invalid_base64")
    assert callable(getattr(module, "gen_test_case_short_cookie"))
    assert callable(getattr(module, "gen_test_case_invalid_base64"))
