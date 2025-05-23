from pathlib import Path

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage

from buttercup.seed_gen.utils import extract_code, get_diff_content

EXAMPLE_LIBPNG_PARTIAL_CODEBLOCK = """
I'll create 8 deterministic Python functions that generate valid PNG inputs for the libpng fuzzer. Each function will create a different type of PNG to test various aspects of the library.

```python
def gen_minimal_grayscale_png() -> bytes:
    # Create a minimal 1x1 grayscale PNG
    header = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # "IHDR"
        0x00, 0x00, 0x00, 0x01,  # width=1
    ])
    return header

def gen_rgb_png() -> bytes:
    # Create a 2x2 RGB PNG
    header = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # "IHDR"
    ])
    return header

def gen_16bit_rgb_png() -> bytes:
    # Create a 2x2 16-bit RGB PNG
    header = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00"""  # noqa: E501

EXPECTED_LIBPNG_EXTRACTED_CODEBLOCK = """def gen_minimal_grayscale_png() -> bytes:
    # Create a minimal 1x1 grayscale PNG
    header = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # "IHDR"
        0x00, 0x00, 0x00, 0x01,  # width=1
    ])
    return header

def gen_rgb_png() -> bytes:
    # Create a 2x2 RGB PNG
    header = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # "IHDR"
    ])
    return header
"""


def test_extract_code_no_markdown():
    message = AIMessage(content="This is a message with no markdown blocks")
    with pytest.raises(OutputParserException):
        extract_code(message)


def test_extract_code_single_block():
    message = AIMessage(
        content="Some text before\n```python\nprint('hello')\nprint('hello')\n```\nText after"
    )
    result = extract_code(message)
    assert result == "print('hello')\nprint('hello')\n"


def test_extract_code_multiple_blocks():
    message = AIMessage(
        content=(
            "First block:\n"
            "```python\nprint('first')\n```\n"
            "Middle text\n"
            "```python\nprint('second')\n```"
        )
    )
    result = extract_code(message)
    assert result == "print('second')\n"


def test_extract_code_partial_block_with_complete_functions():
    message = AIMessage(
        content=(
            "Here's some code:\n"
            "```python\n"
            "import os\n"
            "def func1():\n"
            "    return 1\n"
            "\n"
            "def func2():\n"
            "    return 2\n"
            "\n"
            "def last_func():\n"
            "    return"
        )
    )
    result = extract_code(message)
    assert result == "import os\ndef func1():\n    return 1\n\ndef func2():\n    return 2\n"


def test_extract_code_libpng_partial_codeblock():
    message = AIMessage(content=EXAMPLE_LIBPNG_PARTIAL_CODEBLOCK)
    result = extract_code(message)
    assert result == EXPECTED_LIBPNG_EXTRACTED_CODEBLOCK


def test_extract_code_partial_block_with_no_functions():
    message = AIMessage(content=("Here's some code:\n" "```python\n" "print('hello')\n" "x = 1"))
    with pytest.raises(OutputParserException):
        extract_code(message)


@pytest.fixture
def test_get_diff_content(tmp_path: Path):
    """Test getting diff content."""
    patch1 = tmp_path / "patch1.diff"
    patch1.write_text("mock content for patch1")
    patch2 = tmp_path / "patch2.diff"
    patch2.write_text("mock content for patch2")
    diffs = [patch1, patch2]
    # We expect the first diff's content to be returned
    assert get_diff_content(diffs) == "mock content for patch1"


def test_get_diff_content_empty():
    """Test getting diff content with empty list."""
    diffs = []
    assert get_diff_content(diffs) is None
