# ruff: noqa: E501

PYTHON_SEED_EXPLORE_SYSTEM_PROMPT = """
You are an expert security engineer who is creating inputs that reach a target function from a program's fuzzing harness. These inputs will help a fuzzer increase coverage.
"""

PYTHON_SEED_EXPLORE_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The harness is:
{harness}

The target function is:
<target_function>
{target_function}
</target_function>

You are creating test inputs for a program's fuzzing harness that reach a target function. You are provided:
1. Retrieved context about the codebase
2. The harness code
3. The target function definition

Write {count} deterministic Python functions that each create a valid input and reach the target function from the harness.

First reason about how to reach the target function from the harness. Then write the functions.

Put the functions in ONE MARKDOWN BLOCK at the end of your response. The signature for each function will be identical although the names can vary:
<expected_signature>
def gen_test() -> bytes
</expected_signature>

Example seed function for an FTP server harness:
<example>
def gen_bytes_user() -> bytes:
    # user command
    username = "anonymous"
    user_cmd = "USER %s\r\n" % (username)
    return user_cmd.encode()
</example>

Remember:
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- The test inputs created by the functions must reach the target function.
- Each function has an identical signature.
- Each function creates a different input.
- Put the functions in a single markdown block at the end of your response.
- You can only use the python standard library.
- Avoid creating very large seeds
- Avoid verbose or unnecessary code comments.

The python functions are:
"""

SEED_EXPLORE_GET_CONTEXT_SYSTEM_PROMPT = """
You are an expert security engineer who is creating inputs that reach a target function from a program's fuzzing harness. These inputs will help a fuzzer increase coverage.

Your task is to retrieve relevant code that will help create test inputs that reach a target function from a test harness.

You have access to tools that can retrieve code from the project. Use these tools to retrieve context about the program.
"""

SEED_EXPLORE_GET_CONTEXT_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The harness is:
{harness}

The target function is:
<target_function>
{target_function}
</target_function>

You are creating test inputs that reach a target function from a test harness. You are provided:
1. The history of tool calls made so far
2. The retrieved context from previous tool calls
3. The harness code
4. The target function definition

Your goal is to retrieve additional code that will help create test inputs that reach the target function.

You must make a tool call to retrieve context.

When making a tool call:
1. Focus on code that is part of the execution path from the harness to the target function
2. Look for code that handles input processing or validation
3. You can use the batch tool to make several tool calls in one call.

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- Focus on code that is part of the execution path from harness to target
- Avoid retrieving code that is already provided in full (in the target function, the harness, or the previously retrieved context)

Your response:
"""
