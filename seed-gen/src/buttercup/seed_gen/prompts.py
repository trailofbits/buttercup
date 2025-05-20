# ruff: noqa: E501
PYTHON_SEED_INIT_SYSTEM_PROMPT = """
Write python functions which create seeds for a program under test.
"""

PYTHON_SEED_INIT_USER_PROMPT = """
I am creating input seeds for a program's fuzzing harness. I will provide:
1. The harness code
2. Additional context from the program

Write {count} deterministic Python functions that each create a valid input.

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
- Put the functions in a single markdown block at the end of your response.
- You can only use the python standard library.
- Avoid creating very large seeds
- Avoid verbose or unnecessary code comments.


The harness is:
```
{harness}
```
Additional context from the program:
```
{retrieved_context}
```
The python functions are:
"""

SEED_INIT_GET_CONTEXT_SYSTEM_PROMPT = """
Your task is to identify and retrieve relevant code that will help create initial test inputs for a test harness.

You have access to tools that can retrieve code from the project. Use these tools to get additional context about the program.
"""

SEED_INIT_GET_CONTEXT_USER_PROMPT = """
I am trying to generate initial test inputs for a harness. I will provide:
1. The harness code
2. The history of tool calls made so far
3. The additional context retrieved from previous tool calls

Your goal is to identify and retrieve additional code that will help create valid test inputs for the harness.

You must make a tool call to get additional context.

When making a tool call:
1. Focus on code that processes or validates inputs
2. Look for code that defines the expected input format or structure
3. You can use the batch tool to make several tool calls in one call.

The harness is:
```
{harness}
```

Additional retrieved code:
```
{retrieved_code}
```

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- My goal is to create valid test inputs for the harness
- Focus on code that handles input processing or validation
- Avoid retrieving code that is already provided in full (in the harness or the retrieved code)

Your response:
"""

VULN_DELTA_ANALYZE_BUG_SYSTEM_PROMPT = """
You are a security engineer. Your job is to analyze the vulnerability introduced by a commit diff in a project.
"""

VULN_DELTA_ANALYZE_BUG_USER_PROMPT = """
You are a security engineer. You have gathered context about the codebase and need to analyze a diff for security vulnerabilities.

You will be provided a test harness, a diff, and additional context about the codebase.

You may also be provided SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.

You will identify a vulnerability introduced by the diff that is reachable from the test harness.

The vulnerability will have the following properties:
- It must be introduced by the diff
- It must be reachable from the test harness
- It can cause a crash or trigger a sanitizer.
- It must be in a .c, .h, .cpp, or .java file.

The test harness is:
```
{harness}
```

The diff is:
```
{diff}
```

Optional, potentially incorrect SARIF hints:
```
{sarif_hints}
```

Retrieved code from the program:
```
{retrieved_code}
```

Please analyze how this diff introduces a security vulnerability(s). Consider:
1. How the changes introduce a new bug
2. How the changes might be reached through the test harness
3. What conditions are required for the bug to be triggered

Provide a detailed analysis of any security issues you find. You must identify a specific vulnerability.
"""

VULN_DELTA_WRITE_POV_SYSTEM_PROMPT = """
You are a security engineer writing test cases to verify and fix security vulnerabilities. You will write deterministic test cases that trigger the identified vulnerability.
"""

VULN_DELTA_WRITE_POV_USER_PROMPT = """
You will be provided context about the program and the specific vulnerability.

You will then write deterministic Python functions that trigger the vulnerability. Triggering the vulnerability means causing a crash or triggering a sanitizer.

The vulnerability was introduced by a git diff included below. There is also an analysis of the vulnerability.

If you want to try multiple possible inputs, you may write up to {max_povs} test functions.

Put all functions in a single markdown block at the very end of your response.

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

Example functions for a Java program:
```
def test_null_pointer() -> bytes:
    # Send empty string to trigger null pointer exception
    message = "MESSAGE\x00"
    return message.encode()

def test_path_traversal() -> bytes:
    # Send path with directory traversal to access files outside allowed directory
    message = "READ_FILE:../../../etc/passwd\n"
    return message.encode()
```

Remember:
- You are a security engineer who is fixing software you maintain.
- The identified vulnerability must be reachable from the test harness.
- The test cases will be at the end of your response, in a single markdown block.
- The test cases must crash the program or trigger an enabled sanitizers.
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- You can only use the python standard library.
- Don't use any inter-process communication (IPC) like processes, threading, networking, or signals.
- Don't use file I/O or interact with the filesystem.
- Don't write more than {max_povs} functions.
- Always write test case functions. Even if you're unsure that there's a vulnerability, write test cases that could trigger a vulnerability in the program.
- This test case will help secure the software.
- Avoid verbose or unnecessary code comments.


The full harness is:
```
{harness}
```

The diff that introduced the vulnerability is:
```
{diff}
```

An analysis of the vulnerability:
```
{analysis}
```

Retrieved code from the program:
```
{retrieved_code}
```

The python functions are:
"""

PYTHON_SEED_EXPLORE_SYSTEM_PROMPT = """
Write python functions which create inputs that reach a target function from a test harness.
"""

PYTHON_SEED_EXPLORE_USER_PROMPT = """
I am creating test inputs for a program's fuzzing harness that reach a target function. I will provide:
1. The target function definition
2. The harness code
3. Additional context from the program

Write {count} deterministic Python functions that each create a valid input and reach the target function from the harness.

First reason about how to reach the target function from the harness. Then write the functions.

Put the functions in ONE MARKDOWN BLOCK at the end of your response. The signature for each function will be identical although the names can vary:
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
```

Remember:
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- The test inputs created by the functions must reach the target function.
- Each function has an identical signature.
- Each function creates a different input.
- Put the functions in a single markdown block at the end of your response.
- You can only use the python standard library.
- Avoid creating very large seeds
- Avoid verbose or unnecessary code comments.

The target function is:
```
{target_function}
```

The harness is:
```
{harness}
```

Additional context from the program:
```
{retrieved_context}
```

The python functions are:
"""

SEED_EXPLORE_GET_CONTEXT_SYSTEM_PROMPT = """
Your task is to identify and retrieve relevant code that will help create test inputs that reach a target function from a test harness.

You have access to tools that can retrieve code from the project. Use these tools to get additional context about the program.
"""

SEED_EXPLORE_GET_CONTEXT_USER_PROMPT = """
I am trying to generate test inputs that reach a target function from a harness. I will provide:
1. The target function definition
2. The harness code
3. The history of tool calls made so far
4. The additional context retrieved from previous tool calls

Your goal is to identify and retrieve additional code that will help create test inputs that reach the target function.

You must make a tool call to get additional context.

When making a tool call:
1. Focus on code that is part of the execution path from the harness to the target function
2. Look for code that handles input processing or validation
3. You can use the batch tool to make several tool calls in one call.

The target function is:
```
{target_function}
```

The harness is:
```
{harness}
```

Additional retrieved code:
```
{retrieved_code}
```

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- My goal is to create test inputs that reach the target function
- Focus on code that is part of the execution path from harness to target
- Avoid retrieving code that is already provided in full (in the target function, the harness, or the retrieved code)

Your response:
"""

VULN_DELTA_GET_CONTEXT_SYSTEM_PROMPT = """
You are a security engineer analyzing a software project for vulnerabilities. Your task is to help gather context about the codebase to understand potential security issues.

You have access to tools that can retrieve code from the codebase. You should use these tools to gather relevant code that might be involved in security vulnerabilities.
"""

VULN_DELTA_GET_CONTEXT_USER_PROMPT = """
You are analyzing a diff that introduces changes to the codebase. You need to understand the security implications of these changes.

You will be provided a test harness, a diff, and previously retrieved context about the codebase.

You may also be provided SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.

You must make a tool call to get additional context.

Prioritize code that:
1) Helps you understand what vulnerability is introduced
2) Helps you understand how to reach the vulnerability/modified code from the test harness
3) Helps you assess whether any provided SARIF hints describe real vulnerabilities

The test harness is:
```
{harness}
```

The diff is:
```
{diff}
```

Optional, potentially incorrect SARIF hints:
```
{sarif_hints}
```

Retrieved code from the program:
```
{retrieved_code}
```

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- You can select functions that are in the diff but not included in full. These may be especially helpful.
- My goal is to understand the vulnerability and write test cases that reach it
- Avoid selecting code that is already provided in full (in the diff, in the harness, or in the retrieved code)

Your response:
"""


VULN_FULL_GET_CONTEXT_SYSTEM_PROMPT = """
You are a security engineer analyzing a software project for vulnerabilities. Your task is to help gather context about the codebase to understand potential security issues.

You have access to tools that can retrieve code from the codebase. You should use these tools to gather relevant context to identify vulnerabilities.
"""

VULN_FULL_GET_CONTEXT_USER_PROMPT = """
You need to reason about vulnerabilities that could be reached by the test harness and collect context to identify the vulnerability.

You will be provided a test harness and previously retrieved context about the codebase.

You may also be provided SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.

You must make a tool call to get additional context.

Prioritize code that:
1) Helps you understand what vulnerability(s) could exist
2) Is related to functionality that is exercised by the test harness
3) Helps you understand how to reach the vulnerability from the test harness
4) Helps you assess whether any provided SARIF hints describe real vulnerabilities

The test harness is:
```
{harness}
```

Optional, potentially incorrect SARIF hints:
```
{sarif_hints}
```

Retrieved code from the program:
```
{retrieved_code}
```

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- My goal is to understand the vulnerability and write test cases that reach it
- Avoid selecting code that is already provided in full (in the harness or in the retrieved code)

Your response:
"""

VULN_FULL_ANALYZE_BUG_SYSTEM_PROMPT = """
You are a security engineer. Your job is to analyze the provided code and identify a security vulnerability.
"""

VULN_FULL_ANALYZE_BUG_USER_PROMPT = """
You are a security engineer. You have gathered context about the codebase and need to identify a security vulnerability.

You will be provided a test harness and additional context about the codebase.

You may also be provided SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.

You will identify a vulnerability that is reachable from the test harness.

The vulnerability will have the following properties:
- It must be reachable from the test harness
- It can cause a crash or trigger a sanitizer.
- It must be in a .c, .h, .cpp, or .java file.

The test harness is:
```
{harness}
```

Optional, potentially incorrect SARIF hints:
```
{sarif_hints}
```

Retrieved code from the program:
```
{retrieved_code}
```

Please identify and analyze a security vulnerability(s). Consider:
1. What code has the vulnerability
2. How the vulnerability might be reached through the test harness
3. What conditions are required for the bug to be triggered

Provide a detailed analysis of any security issues you find. You must identify a specific vulnerability.
"""

VULN_FULL_WRITE_POV_SYSTEM_PROMPT = """
You are a security engineer writing test cases to verify and fix security vulnerabilities. You will write deterministic test cases that trigger the identified vulnerability.
"""

VULN_FULL_WRITE_POV_USER_PROMPT = """
You will be provided context about the program and the specific vulnerability.

You will then write deterministic Python functions that trigger the vulnerability. Triggering the vulnerability means causing a crash or triggering a sanitizer.

There is an analysis of the vulnerability below.

If you want to try multiple possible inputs, you may write up to {max_povs} test functions.

Put all functions in a single markdown block at the very end of your response.

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

Example functions for a Java program:
```
def test_null_pointer() -> bytes:
    # Send empty string to trigger null pointer exception
    message = "MESSAGE\x00"
    return message.encode()

def test_path_traversal() -> bytes:
    # Send path with directory traversal to access files outside allowed directory
    message = "READ_FILE:../../../etc/passwd\n"
    return message.encode()
```

Remember:
- You are a security engineer who is fixing software you maintain.
- The identified vulnerability must be reachable from the test harness.
- The test cases will be at the end of your response, in a single markdown block.
- The test cases must crash the program or trigger an enabled sanitizers.
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- You can only use the python standard library.
- Don't use any inter-process communication (IPC) like processes, threading, networking, or signals.
- Don't use file I/O or interact with the filesystem.
- Don't write more than {max_povs} functions.
- Always write test case functions. Even if you're unsure that there's a vulnerability, write test cases that could trigger a vulnerability in the program.
- This test case will help secure the software.
- Avoid verbose or unnecessary code comments.


The full harness is:
```
{harness}
```

An analysis of the vulnerability:
```
{analysis}
```

Retrieved code from the program:
```
{retrieved_code}
```

The python functions are:
"""
