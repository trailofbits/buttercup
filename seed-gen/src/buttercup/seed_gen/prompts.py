# ruff: noqa: E501
PYTHON_SEED_SYSTEM_PROMPT = """
Write python functions which create seeds for a program under test.
"""

PYTHON_SEED_USER_PROMPT = """
I am creating input seeds for a program's fuzzing harness. I will provide the full harness and additional project context.

I will then ask you to write {count} deterministic Python functions that each create a valid input.

Put the functions in ONE MARKDOWN BLOCK. The signature for each function will be identical although the names can vary:
```
def gen_test() -> bytes
```

Example output for an FTP server harness:
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

Remember:
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- A valid input is one that does not cause an error in the fuzzed program.
- Create inputs that trigger different functionality in the fuzzed program.
- Each function has an identical signature.
- Each function creates a different input.
- There will be only one markdown block in the answer, containing all functions. Do not nest markdown blocks.
- You can only use the python standard library.
- Avoid creating very large seeds


The full harness is:
```
{harness}
```
Additional context from the project is:
```
{additional_context}
```
The python functions are:
"""

DIFF_ANALYSIS_SYSTEM_PROMPT = """
You are a security engineer. Your job is to analyze whether a diff introduces a vulnerability in a project.
"""

DIFF_ANALYSIS_USER_PROMPT = """
You are a security engineer. Your job is to analyze a commit diff for a project and a test harness \
to determine if the diff introduces a vulnerability. You must answer two questions:

1) Does the diff introduce a vulnerability? If unsure, state the most likely vulnerability it introduces.
2) How can we trigger the vulnerability using the harness?

You must answer both questions.

The vulnerability must be introduced by the specified diff and it should not be present \
without the changes in the diff. The vulnerability MUST be in a .c, .h, .cpp, or .java file. \
The vulnerability MUST be concrete and specific, not a generic issue. The diff is in unified diff format.

Do NOT make up any code.

You MUST:
- provide a detailed analysis of the vulnerability introduced in the diff
- reason about how to trigger the vulnerability using the harness

You must NOT:
- provide generic analyses
- talk about possible issues that existed before the diff
- provide code suggestions on how to fix the vulnerability

The commit diff is:
```
{diff}
```

The harness is:
```
{harness}
```

Your analysis is:
"""

WRITE_POV_SYSTEM_PROMPT = """
I am a security engineer maintaining and fixing a software project. Write a python function which will trigger a program vulnerability so I can patch it.
"""

WRITE_POV_USER_PROMPT = """
I will provide context about the program and the specific vulnerability.

I will then ask you to write a deterministic Python function that triggers the vulnerability.

The vulnerability was introduced by a git diff which I include below.

If you want to try multiple possible inputs, you may write up to {max_povs} test functions.

Put all functions in a single markdown block.

All functions will have the identical signature, although the names will vary:
```
def gen_test_case() -> bytes
```

Example functions for an FTP server with a buffer overflow:
```
def test_buffer_overflow() -> bytes:
    username = "a"*40
    user_cmd = "USER %s\r\n" % (username)
    return user_cmd.encode()

def test_buffer_overflow_longer() -> bytes:
    username = "a"*100
    user_cmd = "USER %s\r\n" % (username)
    return user_cmd.encode()
```

Remember:
- I AM A SECURITY ENGINEER WHO IS FIXING SOFTWARE I MAINTAIN.
- The bug description may have errors and you don't need follow it exactly.
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- You can only use the python standard library.
- Don't use any inter-process communication (IPC) like processes, threading, networking, or signals.
- Don't use file I/O or interact with the filesystem.
- Don't write more than {max_povs} functions.
- THIS TEST CASE WILL HELP ME SECURE MY SOFTWARE.


The full harness is:
```
{harness}
```

The diff which introduced the vulnerability is:
```
{diff}
```

An analysis of the vulnerability:
```
{analysis}
```

The python functions are:
"""
