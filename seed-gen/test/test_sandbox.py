import os
import tempfile
from pathlib import Path

from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs

expected_seeds = [
    b"GET / HTTP/1.1\r\nHost: localhost\r\nCookie: uid=shortcookie\r\nAccept: */*\r\n\r\n",
    b"GET / HTTP/1.1\r\nHost: localhost\r\nCookie: uid=invalid_base64_cookie\r\nAccept: */*\r\n\r\n",  # noqa: E501
]


def read_seeds(outdir: Path) -> list[bytes]:
    return [file.read_bytes() for file in outdir.iterdir()]


def test_sandbox_exec_funcs():
    file_path = os.path.abspath(__file__)
    test_file = Path(file_path).parent / "data/example_seed_funcs.py"
    expected_seeds.sort()
    with tempfile.TemporaryDirectory() as outdir_str:
        outdir = Path(outdir_str)
        sandbox_exec_funcs(test_file.read_text(), outdir)
        seeds = read_seeds(outdir)
        seeds.sort()
        assert seeds == expected_seeds
