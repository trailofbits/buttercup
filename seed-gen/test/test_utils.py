from langchain_core.messages import AIMessage

from buttercup.seed_gen.utils import extract_md


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
