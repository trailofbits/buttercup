"""Tests for the Software Engineer agent's code snippet parsing functionality."""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from buttercup.patcher.agents.common import ContextCodeSnippet
from buttercup.patcher.agents.swe import (
    CodeSnippetChange,
    CodeSnippetChanges,
    CodeSnippetKey,
    PatcherAgentName,
    PatcherAgentState,
    SWEAgent,
)
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.utils import PatchInputPoV

# ruff: noqa: E501, W293

PNGRUTIL_C_CODE = """
      return;
   }

   (void)png_colorspace_set_sRGB(png_ptr, &png_ptr->colorspace, intent);
   png_colorspace_sync(png_ptr, info_ptr);
}
#endif /* READ_sRGB */

#ifdef PNG_READ_iCCP_SUPPORTED
void /* PRIVATE */
png_handle_iCCP(png_structrp png_ptr, png_inforp info_ptr, png_uint_32 length)
/* Note: this does not properly handle profiles that are > 64K under DOS */
{
   png_const_charp errmsg = NULL; /* error message output, or no error */
   int finished = 0; /* crc checked */

   png_debug(1, "in png_handle_iCCP");

   if ((png_ptr->mode & PNG_HAVE_IHDR) == 0)
      png_chunk_error(png_ptr, "missing IHDR");

   else if ((png_ptr->mode & (PNG_HAVE_IDAT|PNG_HAVE_PLTE)) != 0)
   {
      png_crc_finish(png_ptr, length);
      png_chunk_benign_error(png_ptr, "out of place");
      return;
   }

   /* Consistent with all the above colorspace handling an obviously *invalid*
    * chunk is just ignored, so does not invalidate the color space.  An
    * alternative is to set the 'invalid' flags at the start of this routine
    * and only clear them in they were not set before and all the tests pass.
    */

   /* The keyword must be at least one character and there is a
    * terminator (0) byte and the compression method byte, and the
    * 'zlib' datastream is at least 11 bytes.
    */
   if (length < 14)
   {
      png_crc_finish(png_ptr, length);
      png_chunk_benign_error(png_ptr, "too short");
      return;
   }

   /* If a colorspace error has already been output skip this chunk */
   if ((png_ptr->colorspace.flags & PNG_COLORSPACE_INVALID) != 0)
   {
      png_crc_finish(png_ptr, length);
      return;
   }

   /* Only one sRGB or iCCP chunk is allowed, use the HAVE_INTENT flag to detect
    * this.
    */
   if ((png_ptr->colorspace.flags & PNG_COLORSPACE_HAVE_INTENT) == 0)
   {
      uInt read_length, keyword_length;
      uInt max_keyword_wbytes = 41;
      wpng_byte keyword[max_keyword_wbytes];

      /* Find the keyword; the keyword plus separator and compression method
       * bytes can be at most 41 wide characters long.
       */
      read_length = sizeof(keyword); /* maximum */
      if (read_length > length)
         read_length = (uInt)length;

      png_crc_read(png_ptr, (png_bytep)keyword, read_length);
      length -= read_length;

      /* The minimum 'zlib' stream is assumed to be just the 2 byte header,
       * 5 bytes minimum 'deflate' stream, and the 4 byte checksum.
       */
      if (length < 11)
      {
         png_crc_finish(png_ptr, length);
         png_chunk_benign_error(png_ptr, "too short");
         return;
      }

      keyword_length = 0;
      while (keyword_length < (read_length-1) && keyword_length < read_length &&
         keyword[keyword_length] != 0)
         ++keyword_length;

      /* TODO: make the keyword checking common */
      if (keyword_length >= 1 && keyword_length <= (read_length-2))
      {
         /* We only understand '0' compression - deflate - so if we get a
          * different value we can't safely decode the chunk.
          */
         if (keyword_length+1 < read_length &&
            keyword[keyword_length+1] == PNG_COMPRESSION_TYPE_BASE)
         {
            read_length -= keyword_length+2;

            if (png_inflate_claim(png_ptr, png_iCCP) == Z_OK)
            {
               Byte profile_header[132]={0};
               Byte local_buffer[PNG_INFLATE_BUF_SIZE];
               png_alloc_size_t size = (sizeof profile_header);

               png_ptr->zstream.next_in = (Bytef*)keyword + (keyword_length+2);
               png_ptr->zstream.avail_in = read_length;
               (void)png_inflate_read(png_ptr, local_buffer,
                   (sizeof local_buffer), &length, profile_header, &size,
                   0/*finish: don't, because the output is too small*/);

               if (size == 0)
               {
                  /* We have the ICC profile header; do the basic header checks.
                   */
                  png_uint_32 profile_length = png_get_uint_32(profile_header);

                  if (png_icc_check_length(png_ptr, &png_ptr->colorspace,
                      (char*)keyword, profile_length) != 0)
                  {
                     /* The length is apparently ok, so we can check the 132
                      * byte header.
                      */
                     if (png_icc_check_header(png_ptr, &png_ptr->colorspace,
                         (char*)keyword, profile_length, profile_header,
                         png_ptr->color_type) != 0)
                     {
                        /* Now read the tag table; a variable size buffer is
                         * needed at this point, allocate one for the whole
                         * profile.  The header check has already validated
                         * that none of this stuff will overflow.
                         */
                        png_uint_32 tag_count =
                           png_get_uint_32(profile_header + 128);
                        png_bytep profile = png_read_buffer(png_ptr,
                            profile_length, 2/*silent*/);

                        if (profile != NULL)
                        {
                           memcpy(profile, profile_header,
                               (sizeof profile_header));

                           size = 12 * tag_count;

                           (void)png_inflate_read(png_ptr, local_buffer,
                               (sizeof local_buffer), &length,
                               profile + (sizeof profile_header), &size, 0);
"""

original_subprocess_run = subprocess.run


def mock_docker_run(challenge_task: ChallengeTask):
    def wrapped(args, *rest, **kwargs):
        if args[0] == "docker":
            # Mock docker cp command by copying source path to container src dir
            if args[1] == "cp":
                container_dst_dir = Path(args[3]) / "src" / challenge_task.task_meta.project_name
                container_dst_dir.mkdir(parents=True, exist_ok=True)
                # Copy source files to container src dir
                src_path = challenge_task.get_source_path()
                shutil.copytree(src_path, container_dst_dir, dirs_exist_ok=True)
            elif args[1] == "create" or args[1] == "rm":
                pass

            return subprocess.CompletedProcess(args, returncode=0)
        return original_subprocess_run(args, *rest, **kwargs)

    return wrapped


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=BaseChatModel)
    llm.__or__.return_value = llm
    return llm


@pytest.fixture(autouse=True)
def mock_llm_functions(mock_llm: MagicMock):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_llm),
        patch("buttercup.common.llm.create_llm", return_value=mock_llm),
        patch("langgraph.prebuilt.chat_agent_executor._get_prompt_runnable", return_value=mock_llm),
    ):
        import buttercup.patcher.agents.swe

        buttercup.patcher.agents.swe.SUMMARIZE_PATCH_STRATEGY_PROMPT = mock_llm
        yield


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    tmp_path = tmp_path / "test-challenge-task"
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "libpng"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "libpng" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("""name: libpng
language: c
""")

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.c file
    (source / "test.c").write_text("int foo() { return 0; }\nint main() { int a = foo(); return a; }")
    (source / "test.h").write_text("struct ebitmap_t { int a; };")
    (source / "pngrutil.c").write_text(PNGRUTIL_C_CODE)

    TaskMeta(
        project_name="libpng",
        focus="libpng",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def mock_challenge(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


@pytest.fixture
def swe_agent(mock_challenge: ChallengeTask, tmp_path: Path) -> SWEAgent:
    patch_input = PatchInput(
        challenge_task_dir=mock_challenge.task_dir,
        task_id=mock_challenge.task_meta.task_id,
        internal_patch_id="submission-index-challenge-task",
        povs=[
            PatchInputPoV(
                challenge_task_dir=mock_challenge.task_dir,
                sanitizer="address",
                pov=tmp_path / "pov.c",
                pov_token="pov-token-challenge-task",
                sanitizer_output="sanitizer-output-challenge-task",
                engine="libfuzzer",
                harness_name="my-harness",
            ),
        ],
    )
    return SWEAgent(
        challenge=mock_challenge,
        input=patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
    )


@pytest.fixture
def patcher_agent_state(swe_agent: SWEAgent) -> PatcherAgentState:
    """Create a PatcherAgentState instance."""
    code_snippet = ContextCodeSnippet(
        key=CodeSnippetKey(file_path="/src/libpng/pngrutil.c", identifier="png_handle_iCCP"),
        code=PNGRUTIL_C_CODE,
        start_line=1,
        end_line=1,
    )
    return PatcherAgentState(
        context=swe_agent.input,
        messages=[],
        relevant_code_snippets=[code_snippet],
    )


def test_code_snippet_change_parse_single_pair():
    """Test parsing a single old_code/new_code pair from a patch block."""
    patch_block = """
    <patch>
    <file_path>test/file/path.py</file_path>
    <identifier>old_function</identifier>
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
    assert change.key.file_path == "test/file/path.py"
    assert change.key.identifier == "old_function"
    assert "def old_function():" in change.old_code
    assert "def new_function():" in change.code
    assert change.is_valid()


def test_code_snippet_change_parse_multiple_pairs():
    """Test parsing multiple old_code/new_code pairs from a patch block."""
    patch_block = """
    <patch>
    <file_path>test/file/path.py</file_path>
    <identifier>old_function1</identifier>
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
    assert change1.key.identifier == "old_function1"
    assert change1.key.file_path == "test/file/path.py"
    assert "def old_function1():" in change1.old_code
    assert "def new_function1():" in change1.code
    assert change1.is_valid()

    # Check second pair
    change2 = result[1]
    assert change2.key.identifier == "old_function1"
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
    <identifier>old_function</identifier>
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
    <identifier>old_function</identifier>
    <file_path>test/file/path.py</file_path>
    </patch>
    """

    result = CodeSnippetChange.parse(patch_block)
    assert len(result) == 0


def test_code_snippet_change_oneline():
    """Test parsing a patch block where the msg is a single line."""
    msg = """
    <patch>
    <identifier>old_function</identifier>
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
    assert result[0].key.identifier == "old_function"
    assert result[0].key.file_path == "test/file/path.py"


def test_code_snippet_changes_parse_multiple_patches():
    """Test parsing multiple patch blocks."""
    msg = """
    <patch>
    <identifier>old_function1</identifier>
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
    <identifier>old_function2</identifier>
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
    assert change1.key.identifier == "old_function1"
    assert change1.key.file_path == "test/file/path1.py"
    assert "def old_function1():" in change1.old_code
    assert "def new_function1():" in change1.code
    assert change1.is_valid()

    # Check second patch
    change2 = result.items[1]
    assert change2.key.identifier == "old_function2"
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
        key=CodeSnippetKey(file_path="test/file/path.py", identifier="old_function"),
        old_code="def old_function(): return 'old'",
        code="def new_function(): return 'new'",
    )
    assert valid_change.is_valid()

    # Missing file_path
    invalid_change1 = CodeSnippetChange(
        key=CodeSnippetKey(file_path="", identifier="old_function"),
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
        key=CodeSnippetKey(file_path="test/file/path.py", identifier="old_function"),
        old_code=None,
        code="def new_function(): return 'new'",
    )
    assert not invalid_change3.is_valid()

    # Missing code
    invalid_change4 = CodeSnippetChange(
        key=CodeSnippetKey(file_path="test/file/path.py", identifier="old_function"),
        old_code="def old_function(): return 'old'",
        code=None,
    )
    assert not invalid_change4.is_valid()


def test_code_snippet_changes_parse_real():
    msg = """<explanation>
The changes I intend to make involve adjusting the logic to ensure that the `read_length` does not exceed the buffer size of 41 wide characters. This will involve modifying the calculation of `read_length` to be the minimum of the buffer size and the remaining length of the data. Additionally, I will ensure that the while loop condition properly checks the bounds to prevent reading beyond the buffer's allocated size. These changes will fix the vulnerability by preventing the buffer overflow condition that was introduced by the reduction in buffer size.
</explanation>

<patch>
<identifier>png_handle_iCCP</identifier>
<file_path>/src/libpng/pngrutil.c</file_path>
<old_code>
      read_length = sizeof(keyword); /* maximum */
      if (read_length > length)
         read_length = (uInt)length;

      png_crc_read(png_ptr, (png_bytep)keyword, read_length);
      length -= read_length;

      keyword_length = 0;
      while (keyword_length < (read_length-1) && keyword_length < read_length &&
         keyword[keyword_length] != 0)
         ++keyword_length;
</old_code>
<new_code>
      read_length = max_keyword_wbytes - 1; /* ensure space for null terminator */
      if (read_length > length)
         read_length = (uInt)length;

      png_crc_read(png_ptr, (png_bytep)keyword, read_length);
      length -= read_length;

      keyword_length = 0;
      while (keyword_length < read_length && keyword[keyword_length] != 0)
         ++keyword_length;
</new_code>
</patch>
    """

    result = CodeSnippetChanges.parse(msg)

    assert result.items is not None
    assert len(result.items) == 1
    assert result.items[0].key.identifier == "png_handle_iCCP"
    assert result.items[0].key.file_path == "/src/libpng/pngrutil.c"
    assert result.items[0].old_code is not None
    assert result.items[0].code is not None
    assert "read_length = sizeof(keyword); /* maximum */" in result.items[0].old_code
    assert "read_length = max_keyword_wbytes - 1; /* ensure space for null terminator */" in result.items[0].code
    assert (
        "      while (keyword_length < (read_length-1) && keyword_length < read_length &&" in result.items[0].old_code
    )
    assert "      while (keyword_length < read_length && keyword[keyword_length] != 0)" in result.items[0].code


def test_create_upatch_no_oldcode(swe_agent: SWEAgent, patcher_agent_state: PatcherAgentState):
    old_code = """
      read_length = sizeof(keyword); /* maximum */
      if (read_length > length)
         read_length = (uInt)length;

      png_crc_read(png_ptr, (png_bytep)keyword, read_length);
      length -= read_length;

      keyword_length = 0;
      while (keyword_length < (read_length-1) && keyword_length < read_length &&
         keyword[keyword_length] != 0)
         ++keyword_length;
"""
    new_code = """
      read_length = max_keyword_wbytes - 1; /* ensure space for null terminator */
      if (read_length > length)
         read_length = (uInt)length;

      png_crc_read(png_ptr, (png_bytep)keyword, read_length);
      length -= read_length;

      keyword_length = 0;
      while (keyword_length < read_length && keyword[keyword_length] != 0)
         ++keyword_length;
"""
    changes = CodeSnippetChanges(
        items=[
            CodeSnippetChange(
                key=CodeSnippetKey(file_path="/src/libpng/pngrutil.c", identifier="png_handle_iCCP"),
                old_code=old_code,
                code=new_code,
            ),
        ],
    )
    patch = swe_agent.create_upatch(patcher_agent_state, changes)
    assert patch is None


def test_select_patch_strategy_basic(swe_agent: SWEAgent, patcher_agent_state: PatcherAgentState, mock_llm: MagicMock):
    """Test the select_patch_strategy method for a basic successful patch strategy selection."""
    # Mock the LLM to return a valid patch strategy string
    patch_strategy_str = (
        "<full_description>This is a detailed patch strategy.</full_description><summary>Short summary.</summary>"
    )
    swe_agent.patch_strategy_chain = MagicMock()
    swe_agent.patch_strategy_chain.invoke.return_value = patcher_agent_state
    patcher_agent_state.messages = [AIMessage(content=patch_strategy_str)]

    mock_llm.invoke.side_effect = ["This is a summarized patch strategy."]

    # Call the method
    config = None  # Not used in the test
    command = swe_agent.select_patch_strategy(patcher_agent_state, config)

    # Check that the command is correct
    assert hasattr(command, "update")
    assert "patch_strategy" in command.update
    assert command.update["patch_strategy"].full == "This is a detailed patch strategy."
    assert command.update["patch_strategy"].summary == "This is a summarized patch strategy."
    assert command.goto == PatcherAgentName.CREATE_PATCH.value


def test_select_patch_strategy_summary_error(
    swe_agent: SWEAgent,
    patcher_agent_state: PatcherAgentState,
    mock_llm: MagicMock,
):
    """Test the select_patch_strategy method for errors in summary generation."""
    patch_strategy_str = (
        "<full_description>This is a detailed patch strategy.</full_description><summary>Short summary.</summary>"
    )
    swe_agent.patch_strategy_chain = MagicMock()
    swe_agent.patch_strategy_chain.invoke.return_value = patcher_agent_state
    patcher_agent_state.messages = [AIMessage(content=patch_strategy_str)]

    mock_llm.invoke.side_effect = [
        None,
    ]

    # Call the method
    config = None  # Not used in the test
    command = swe_agent.select_patch_strategy(patcher_agent_state, config)

    # Check that the command is correct
    assert hasattr(command, "update")
    assert "patch_strategy" in command.update
    assert command.update["patch_strategy"].full == "This is a detailed patch strategy."
    assert command.update["patch_strategy"].summary == "Short summary."
    assert command.goto == PatcherAgentName.CREATE_PATCH.value


def test_select_patch_strategy_no_full(
    swe_agent: SWEAgent,
    patcher_agent_state: PatcherAgentState,
    mock_llm: MagicMock,
):
    """Test the select_patch_strategy method for incorrect output"""
    patch_strategy_str = "This is a detailed patch strategy."
    swe_agent.patch_strategy_chain = MagicMock()
    swe_agent.patch_strategy_chain.invoke.return_value = patcher_agent_state
    patcher_agent_state.messages = [AIMessage(content=patch_strategy_str)]

    mock_llm.invoke.side_effect = [
        None,
    ]

    # Call the method
    config = None  # Not used in the test
    command = swe_agent.select_patch_strategy(patcher_agent_state, config)

    # Check that the command is correct
    assert hasattr(command, "update")
    assert "patch_strategy" in command.update
    assert command.update["patch_strategy"].full == "This is a detailed patch strategy."
    assert command.update["patch_strategy"].summary == "This is a detailed patch strategy."
    assert command.goto == PatcherAgentName.CREATE_PATCH.value


def test_select_patch_strategy_no_full_correct_summary(
    swe_agent: SWEAgent,
    patcher_agent_state: PatcherAgentState,
    mock_llm: MagicMock,
):
    """Test that the summary generation is done on the correct full description"""
    patch_strategy_str = "This is a detailed patch strategy."
    swe_agent.patch_strategy_chain = MagicMock()
    swe_agent.patch_strategy_chain.invoke.return_value = patcher_agent_state
    patcher_agent_state.messages = [AIMessage(content=patch_strategy_str)]

    mock_llm.invoke.side_effect = [
        "Short description",
    ]

    # Call the method
    config = None  # Not used in the test
    command = swe_agent.select_patch_strategy(patcher_agent_state, config)

    # Check that the command is correct
    assert hasattr(command, "update")
    assert "patch_strategy" in command.update
    assert command.update["patch_strategy"].full == "This is a detailed patch strategy."
    assert command.update["patch_strategy"].summary == "Short description"
    mock_llm.invoke.assert_called_with({"patch_strategy": patch_strategy_str})
    assert command.goto == PatcherAgentName.CREATE_PATCH.value
