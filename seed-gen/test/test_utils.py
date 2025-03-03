from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from buttercup.seed_gen.utils import extract_md, get_diff_content


def test_extract_md_no_markdown():
    message = AIMessage(content="This is a message with no markdown blocks")
    result = extract_md(message)
    assert result == "This is a message with no markdown blocks"


def test_extract_md_single_block():
    message = AIMessage(
        content="Some text before\n```python\nprint('hello')\nprint('hello')\n```\nText after"
    )
    result = extract_md(message)
    assert result == "print('hello')\nprint('hello')\n"


def test_extract_md_multiple_blocks():
    message = AIMessage(
        content=(
            "First block:\n"
            "```python\nprint('first')\n```\n"
            "Middle text\n"
            "```python\nprint('second')\n```"
        )
    )
    result = extract_md(message)
    assert result == "print('second')\n"


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
