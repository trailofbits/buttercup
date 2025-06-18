# ruff: noqa: E501
PYTHON_SEED_INIT_SYSTEM_PROMPT = """
You are an expert security engineer who is fuzzing a program via a test harness. Write python functions to create seeds that bootstrap the fuzzer's corpus.
"""

PYTHON_SEED_INIT_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The harness is:
{harness}

You are creating seed inputs to bootstrap the fuzzing corpus for a program's test harness. You are provided:
1. Retrieved context about the codebase
2. The harness code

Write {count} deterministic Python functions that each create a valid input for the harness.

Put the functions in ONE MARKDOWN BLOCK. The signature for each function will be identical although the names can vary:
<expected_signature>
def gen_test() -> bytes
</expected_signature>

Example output for an FTP server harness:
<example>
```
def gen_bytes_user() -> bytes:
    # user command
    username = "anonymous"
    user_cmd = "USER %s\r\n" % (username)
    return user_cmd.encode()

def gen_bytes_pass() -> bytes:
    # pass command
    password = "mypassword"
    pass_cmd = "PASS %s\r\n" % (password)
    return pass_cmd.encode()
```
</example>

Remember:
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- A valid input is one that does not cause an error in the fuzzed program.
- Create inputs that trigger different functionality in the fuzzed program.
- Each function has an identical signature.
- Each function creates a different input.
- Put the functions in a single markdown block at the end of your response.
- You can only use the python standard library.
- Avoid creating very large seeds
- Avoid verbose or unnecessary code comments.

The python functions are:
"""

SEED_INIT_GET_CONTEXT_SYSTEM_PROMPT = """
You are an expert security engineer who is creating seed inputs for a fuzzing corpus.

Your task is to retrieve relevant code that will help you create high-quality inputs for the harness.

You have access to tools that can retrieve code from the project. Use these tools to retrieve context about the program.
"""

SEED_INIT_GET_CONTEXT_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The harness is:
{harness}

You are creating seed inputs to bootstrap the fuzzing corpus for a program's test harness. You are provided:
1. The history of tool calls made so far
2. The retrieved context from previous tool calls
3. The harness code

Your goal is to retrieve additional code that will help create high-quality seeds for the harness.

You must make a tool call to retrieve context.

When making a tool call:
1. Focus on code that processes or validates inputs
2. Look for code that defines the expected input format or structure
3. You can use the batch tool to make several tool calls in one call.

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- Focus on code that handles input processing or is relevant to the functionality tested by the harness.
- Avoid retrieving code that is already provided in full (in the harness or the previously retrieved context)

Your response:
"""
