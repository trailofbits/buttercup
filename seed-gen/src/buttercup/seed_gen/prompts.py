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

When using the tools:
1. Focus on code that processes or validates inputs
2. Look for code that defines the expected input format or structure
3. Make up to {max_calls} tool calls to gather context

The harness is:
```
{harness}
```

Additional retrieved code:
```
{retrieved_code}
```

Remember:
- Make up to {max_calls} tool calls to gather context. These calls are in addition to the ones already made.
- My goal is to create valid test inputs for the harness
- Focus on code that handles input processing or validation
- Avoid retrieving code that is already provided in full (in the harness or the retrieved code)
- If it's a Java program and you're retrieving a method, only specify the method name without the class prefix. For example, if the method is `example.MyClass.myMethod`, only specify `myMethod`.

Your response:
"""

DIFF_ANALYSIS_SYSTEM_PROMPT = """
You are a security engineer. Your job is to analyze the vulnerability introduced by a commit diff in a project.
"""

DIFF_ANALYSIS_USER_PROMPT = """
You are a security engineer. Your job is to analyze the vulnerability introduced by a commit diff.

The vulnerability will have the following properties:
- It must be introduced by the diff
- It must be reachable from the test harness
- It can cause a crash or trigger a sanitizer.
- It must be in a .c, .h, .cpp, or .java file.

I will provide the diff and the harness. I will also provide additional function definitions which may be helpful for analyzing the vulnerability.

You will then identify the vulnerability and analyze it.

The analysis should:
- Identify and analyze a specific vulnerability, instead of a generic issue.

The commit diff is:
```
{diff}
```

The harness is:
```
{harness}
```

Additional function definitions:
```
{additional_functions}
```

Your analysis is:
"""

WRITE_POV_SYSTEM_PROMPT = """
I am a security engineer maintaining and fixing a software project. Write test cases which trigger a vulnerability from a test harness.
"""

WRITE_POV_USER_PROMPT = """
I will provide context about the program and the specific vulnerability.

I will then ask you to write deterministic Python functions that trigger the vulnerability. Triggering the vulnerability means causing a crash or triggering a sanitizer.

The vulnerability was introduced by a git diff which I include below. I also include an analysis of the vulnerability.

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
- I AM A SECURITY ENGINEER WHO IS FIXING SOFTWARE I MAINTAIN.
- The identified vulnerability must be reachable from the test harness.
- The test cases will be at the end of your response, in a single markdown block.
- The test cases must crash the program or trigger an enabled sanitizers.
- The functions must create a deterministic sequence of bytes. Do not use things like `random`.
- You can only use the python standard library.
- Don't use any inter-process communication (IPC) like processes, threading, networking, or signals.
- Don't use file I/O or interact with the filesystem.
- Don't write more than {max_povs} functions.
- Always write test case functions. Even if you're unsure that there's a vulnerability, write test cases that could trigger a vulnerability in the program.
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

Additional function definitions which may be helpful:
```
{additional_functions}
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

When using the tools:
1. Focus on code that is part of the execution path from the harness to the target function
2. Look for code that handles input processing or validation
3. Make up to {max_calls} tool calls to gather context

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
- Make up to {max_calls} tool calls to gather context. These calls are in addition to the ones already made.
- My goal is to create test inputs that reach the target function
- Focus on code that is part of the execution path from harness to target
- Avoid retrieving code that is already provided in full (in the target function, the harness, or the retrieved code)
- If it's a Java program and you're retrieving a method, only specify the method name without the class prefix. For example, if the method is `example.MyClass.myMethod`, only specify `myMethod`.

Your response:
"""

VULN_DISCOVERY_FUNCTION_LOOKUP_SYSTEM_PROMPT = """
Identify functions that would be most helpful to analyze a vulnerability introduced by a git diff.
"""

VULN_DISCOVERY_FUNCTION_LOOKUP_USER_PROMPT = """
I am trying to analyze a vulnerability introduced by a git diff and write test cases that reach it from the harness. I will provide:
1. The diff
2. The harness code
3. Any additional function definitions I have already looked up

Please identify 1-{max_lookup_functions} functions based on the provided code which would be most helpful for analyzing the vulnerability and writing test cases that reach it.
I will look up the definition of each function you identify and reference them when analyzing the vulnerability and writing test cases for it.

Provide:
1. The function name
2. A VERY BRIEF explanation of why having this function's code would be helpful for analyzing the vulnerability

Format your response as a JSON array of objects with "name" and "reason" fields. For example:
```
[
    {{"name": "parse_command", "reason": "Handles command parsing which is crucial for reaching the target function"}},
    {{"name": "validate_input", "reason": "Validates inputs before they reach the target function"}}
]
```
Do not specify functions which the provided code already defines in full (functions which are partially cut off are allowed).

If it's a Java program, only specify the method name. Do not prefix it with the class name. For example, if the method is `example.MyClass.myMethod`, only specify `myMethod`.

The diff which introduced the vulnerability is:
```
{diff}
```

The harness is:
```
{harness}
```

Additional function definitions:
```
{additional_functions}
```

Remember:
- Select no more than {max_lookup_functions} functions
- You can select functions that are in the diff but not included in full. These may be especially helpful.
- My goal is to understand the vulnerability and write test cases that reach it
- Answer only with the JSON array of functions, in the format specified above
- Do not select a function where the definition is already provided in full (in the diff, in the harness, or in the additional functions)
- If it's a Java program, only specify the method name. Do not prefix it with the class name.

Your response:
"""
