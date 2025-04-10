"""Tests for the Software Engineer agent's code snippet parsing functionality."""

from buttercup.patcher.agents.swe import CodeSnippetChange, CodeSnippetChanges, CodeSnippetKey


def test_code_snippet_change_parse_single_pair():
    """Test parsing a single old_code/new_code pair from a patch block."""
    patch_block = """
    <patch>
    <identifier>test_identifier</identifier>
    <file_path>test/file/path.py</file_path>
    <old_code>
    def old_function():
        return "old"
    </old_code>
    <new_code>
    def new_function():
        return "new"
    </new_code>
    </patch>
    """

    result = CodeSnippetChange.parse(patch_block)

    assert len(result) == 1
    change = result[0]
    assert change.key.identifier == "test_identifier"
    assert change.key.file_path == "test/file/path.py"
    assert "def old_function():" in change.old_code
    assert "def new_function():" in change.code
    assert change.is_valid()


def test_code_snippet_change_parse_multiple_pairs():
    """Test parsing multiple old_code/new_code pairs from a patch block."""
    patch_block = """
    <patch>
    <identifier>test_identifier</identifier>
    <file_path>test/file/path.py</file_path>
    <old_code>
    def old_function1():
        return "old1"
    </old_code>
    <new_code>
    def new_function1():
        return "new1"
    </new_code>
    <old_code>
    def old_function2():
        return "old2"
    </old_code>
    <new_code>
    def new_function2():
        return "new2"
    </new_code>
    </patch>
    """

    result = CodeSnippetChange.parse(patch_block)

    assert len(result) == 2

    # Check first pair
    change1 = result[0]
    assert change1.key.identifier == "test_identifier"
    assert change1.key.file_path == "test/file/path.py"
    assert "def old_function1():" in change1.old_code
    assert "def new_function1():" in change1.code
    assert change1.is_valid()

    # Check second pair
    change2 = result[1]
    assert change2.key.identifier == "test_identifier"
    assert change2.key.file_path == "test/file/path.py"
    assert "def old_function2():" in change2.old_code
    assert "def new_function2():" in change2.code
    assert change2.is_valid()


def test_code_snippet_change_parse_missing_identifier():
    """Test parsing a patch block with missing identifier."""
    patch_block = """
    <patch>
    <file_path>test/file/path.py</file_path>
    <old_code>
    def old_function():
        return "old"
    </old_code>
    <new_code>
    def new_function():
        return "new"
    </new_code>
    </patch>
    """

    result = CodeSnippetChange.parse(patch_block)
    assert len(result) == 0


def test_code_snippet_change_parse_missing_file_path():
    """Test parsing a patch block with missing file path."""
    patch_block = """
    <patch>
    <identifier>test_identifier</identifier>
    <old_code>
    def old_function():
        return "old"
    </old_code>
    <new_code>
    def new_function():
        return "new"
    </new_code>
    </patch>
    """

    result = CodeSnippetChange.parse(patch_block)
    assert len(result) == 0


def test_code_snippet_change_parse_missing_code_pairs():
    """Test parsing a patch block with no code pairs."""
    patch_block = """
    <patch>
    <identifier>test_identifier</identifier>
    <file_path>test/file/path.py</file_path>
    </patch>
    """

    result = CodeSnippetChange.parse(patch_block)
    assert len(result) == 0


def test_code_snippet_change_oneline():
    """Test parsing a patch block where the msg is a single line."""
    msg = """
    <patch>
    <identifier>test_identifier</identifier>
    <file_path>test/file/path.py</file_path>
    <old_code>
    int old_function() {
        return 1;
    }
    </old_code>
    <new_code>
    int new_function() {
        return 2;
    }
    </new_code>
    </patch>
    """

    msg = msg.replace("\n", "")
    result = CodeSnippetChange.parse(msg)
    assert len(result) == 1
    assert result[0].key.identifier == "test_identifier"
    assert result[0].key.file_path == "test/file/path.py"


def test_code_snippet_changes_parse_multiple_patches():
    """Test parsing multiple patch blocks."""
    msg = """
    <patch>
    <identifier>test_identifier1</identifier>
    <file_path>test/file/path1.py</file_path>
    <old_code>
    def old_function1():
        return "old1"
    </old_code>
    <new_code>
    def new_function1():
        return "new1"
    </new_code>
    </patch>
    
    <patch>
    <identifier>test_identifier2</identifier>
    <file_path>test/file/path2.py</file_path>
    <old_code>
    def old_function2():
        return "old2"
    </old_code>
    <new_code>
    def new_function2():
        return "new2"
    </new_code>
    </patch>
    """

    result = CodeSnippetChanges.parse(msg)

    assert result.items is not None
    assert len(result.items) == 2

    # Check first patch
    change1 = result.items[0]
    assert change1.key.identifier == "test_identifier1"
    assert change1.key.file_path == "test/file/path1.py"
    assert "def old_function1():" in change1.old_code
    assert "def new_function1():" in change1.code
    assert change1.is_valid()

    # Check second patch
    change2 = result.items[1]
    assert change2.key.identifier == "test_identifier2"
    assert change2.key.file_path == "test/file/path2.py"
    assert "def old_function2():" in change2.old_code
    assert "def new_function2():" in change2.code
    assert change2.is_valid()


def test_code_snippet_changes_parse_empty_message():
    """Test parsing an empty message."""
    msg = ""

    result = CodeSnippetChanges.parse(msg)

    assert result.items is not None
    assert len(result.items) == 0


def test_code_snippet_changes_parse_no_patches():
    """Test parsing a message with no patch blocks."""
    msg = "This is a message without any patch blocks."

    result = CodeSnippetChanges.parse(msg)

    assert result.items is not None
    assert len(result.items) == 0


def test_code_snippet_change_is_valid():
    """Test the is_valid method of CodeSnippetChange."""
    # Valid case
    valid_change = CodeSnippetChange(
        key=CodeSnippetKey(file_path="test/file/path.py", identifier="test_identifier"),
        old_code="def old_function(): return 'old'",
        code="def new_function(): return 'new'",
    )
    assert valid_change.is_valid()

    # Missing file_path
    invalid_change1 = CodeSnippetChange(
        key=CodeSnippetKey(file_path="", identifier="test_identifier"),
        old_code="def old_function(): return 'old'",
        code="def new_function(): return 'new'",
    )
    assert not invalid_change1.is_valid()

    # Missing identifier
    invalid_change2 = CodeSnippetChange(
        key=CodeSnippetKey(file_path="test/file/path.py", identifier=""),
        old_code="def old_function(): return 'old'",
        code="def new_function(): return 'new'",
    )
    assert not invalid_change2.is_valid()

    # Missing old_code
    invalid_change3 = CodeSnippetChange(
        key=CodeSnippetKey(file_path="test/file/path.py", identifier="test_identifier"),
        old_code=None,
        code="def new_function(): return 'new'",
    )
    assert not invalid_change3.is_valid()

    # Missing code
    invalid_change4 = CodeSnippetChange(
        key=CodeSnippetKey(file_path="test/file/path.py", identifier="test_identifier"),
        old_code="def old_function(): return 'old'",
        code=None,
    )
    assert not invalid_change4.is_valid()
