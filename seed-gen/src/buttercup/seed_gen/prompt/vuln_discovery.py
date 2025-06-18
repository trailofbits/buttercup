# ruff: noqa: E501
VULN_C_POV_EXAMPLES = r"""
<example>
```
def test_buffer_overflow() -> bytes:
    # Send oversized username to trigger stack buffer overflow
    username = "A" * 256
    user_cmd = "USER %s\r\n" % (username)
    return user_cmd.encode()
```
</example>
<example>
```
def test_heap_overflow() -> bytes:
    # Send oversized password to trigger heap overflow
    password = "B" * 1024
    pass_cmd = "PASS %s\r\n" % (password)
    return pass_cmd.encode()
```
</example>
<example>
```
def test_use_after_free() -> bytes:
    # Send commands to trigger use-after-free
    allocate = "PUT test.txt\r\n"
    free = "DELETE test.txt\r\n"
    use = "READ test.txt\r\n"
    return (allocate + free + use).encode()
```
</example>
"""

VULN_JAVA_POV_EXAMPLES = r"""
<example>
```
def test_deserialization() -> bytes:
    # Send serialized object to trigger deserialization vulnerability
    message = "POST /api/object HTTP/1.1\r\n"
    message += "Content-Type: application/java-serialized-object\r\n"
    message += "Content-Length: 100\r\n\r\n"
    message += "rO0ABXNyABFqYXZhLnV0aWwuSGFzaE1hcAUH2sHDFmDRAwABRgAEbWFwaHQA"  # Base64 encoded serialized object
    return message.encode()
```
</example>
<example>
```
def test_sql_injection() -> bytes:
    # Send SQL injection payload to bypass authentication and extract data
    payload = "' UNION SELECT username,password,2,3 FROM users--"
    message = "GET /api/login?user=" + payload + " HTTP/1.1\r\n"
    return message.encode()
```
</example>
<example>
```
def test_path_traversal() -> bytes:
    # Send path traversal with dynamic depth
    depth = 5
    traversal = "../" * depth
    message = "GET /api/files?path=" + traversal + "etc/shadow HTTP/1.1\r\n"
    return message.encode()
```
</example>
"""

COMMON_CWE_LIST = """CWE-476: NULL Pointer Dereference
CWE-400: Uncontrolled Resource Consumption"""

JAVA_CWE_LIST = """CWE-89: Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')
CWE-78: Improper Neutralization of Special Elements used in an OS Command ('OS Command Injection')
CWE-22: Improper Limitation of a Pathname to a Restricted Directory ('Path Traversal')
CWE-502: Deserialization of Untrusted Data
CWE-77: Improper Neutralization of Special Elements used in a Command ('Command Injection')
CWE-94: Improper Control of Generation of Code ('Code Injection')
CWE-917: Improper Neutralization of Special Elements used in an Expression Language Statement ('Expression Language Injection')
CWE-90: Improper Neutralization of Special Elements used in an LDAP Query ('LDAP Injection')
CWE-470: Use of Externally-Controlled Input to Select Classes or Code ('Unsafe Reflection')
CWE-918: Server-Side Request Forgery (SSRF)
CWE-643: Improper Neutralization of Data within XPath Expressions ('XPath Injection')"""

C_CWE_LIST = """CWE-787: Out-of-bounds Write
CWE-125: Out-of-bounds Read
CWE-119: Improper Restriction of Operations within the Bounds of a Memory Buffer
CWE-416: Use After Free
CWE-415: Double Free
CWE-190: Integer Overflow or Wraparound
CWE-191: Integer Underflow (Wrap or Wraparound)"""

VULN_DELTA_ANALYZE_BUG_SYSTEM_PROMPT = """
You are an expert security engineer. Your job is to analyze the vulnerability introduced by a commit diff in a project.
"""

VULN_DELTA_ANALYZE_BUG_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The test harness is:
{harness}

The diff that introduced the vulnerability is:
<diff>
{diff}
</diff>

Optional, potentially incorrect SARIF hints:
<sarif_hints>
{sarif_hints}
</sarif_hints>

Previous attempts at test cases that failed to trigger the vulnerability:
<previous_attempts>
{previous_attempts}
</previous_attempts>

You will analyze a diff to identify the security vulnerability it introduced in a program. You are provided:
1. Retrieved context about the codebase.
2. The test harness
3. The diff which introduces a security vulnerability
4. (Optional) SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.
5. Any previous attempts that analyzed a vulnerability and wrote python test cases to trigger it. These test cases failed to trigger a vulnerability.

You will identify a vulnerability introduced by the diff that is reachable from the test harness.

The vulnerability will have the following properties:
- It must be introduced by the diff
- It must be reachable from the test harness
- It can cause a crash, trigger a {fuzzer_name} sanitizer, or cause a timeout.
- It must be in a {vuln_files} file.

Consider CWEs when identifying the vulnerability. The following CWEs are the most common ones to look for:
<common_cwe_list>
{cwe_list}
</common_cwe_list>
It's possible a vulnerability is related to a different CWE, so consider other CWEs that aren't listed as well.

Please analyze how this diff introduces a security vulnerability(s). Consider:
1. How the changes introduce a new bug
2. How the changes might be reached through the test harness
3. What conditions are required for the bug to be triggered

Provide a detailed analysis of any security issues you find. You must identify a specific vulnerability and list the CWE(s) it belongs to.

If previous attempts are provided, do the following instead of performing an initial analysis:
1. Concisely explain why previous test cases failed to trigger a vulnerability
2. Suggest specific improvements to the test strategy
"""

VULN_DELTA_WRITE_POV_SYSTEM_PROMPT = """
You are an expert security engineer writing test cases to verify and fix security vulnerabilities. You will write deterministic test cases that trigger the identified vulnerability.
"""

VULN_DELTA_WRITE_POV_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The harness is:
{harness}

The diff that introduced the vulnerability is:
<diff>
{diff}
</diff>

Previous attempts at test cases that failed to trigger the vulnerability:
<previous_attempts>
{previous_attempts}
</previous_attempts>

The latest analysis of the vulnerability:
<latest_analysis>
{analysis}
</latest_analysis>

You will write deterministic Python functions that trigger a vulnerability introduced by a diff. You are provided:
1. Retrieved context about the codebase
2. The test harness
3. The diff which introduces a security vulnerability
4. Previous attempts at test cases which failed to trigger the vulnerability and corresponding analysis from those attempts.
5. The latest analysis of the vulnerability.

Triggering the vulnerability means causing a crash, triggering a {fuzzer_name} sanitizer, or causing a timeout.

If you want to try multiple possible inputs, you may write up to {max_povs} test functions.

Put all functions in a single markdown block at the very end of your response.

All functions will have the identical signature, although the names will vary:
<expected_signature>
def gen_test_case() -> bytes
</expected_signature>

Function examples:
{pov_examples}

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

The python functions are:
"""

VULN_DELTA_GET_CONTEXT_SYSTEM_PROMPT = """
You are an expert security engineer analyzing a software project for vulnerabilities. Your task is to gather context about the codebase to understand potential security issues.

You have access to tools that can retrieve code from the codebase. You should use these tools to gather relevant code that might be involved in security vulnerabilities.
"""

VULN_DELTA_GET_CONTEXT_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The test harness is:
{harness}

The diff that introduced the vulnerability is:
<diff>
{diff}
</diff>

Optional, potentially incorrect SARIF hints:
<sarif_hints>
{sarif_hints}
</sarif_hints>

You are analyzing a diff that introduces changes to the codebase. You need to understand the security implications of these changes.

You are provided:
1. The history of tool calls made so far
2. Retrieved context about the codebase
3. The test harness
4. The diff which introduces a security vulnerability
5. (Optional) SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.

You must make a tool call to retrieve context.

Prioritize code that:
1) Helps you understand what vulnerability is introduced
2) Helps you understand how to reach the vulnerability/modified code from the test harness
3) Helps you assess whether any provided SARIF hints describe real vulnerabilities

The vulnerability will have the following properties:
- It must be introduced by the diff
- It must be reachable from the test harness
- It can cause a crash, trigger a {fuzzer_name} sanitizer, or cause a timeout.
- It must be in a {vuln_files} file.

Consider CWEs when looking for vulnerabilities. The following CWEs are the most common ones to look for:
<common_cwe_list>
{cwe_list}
</common_cwe_list>
It's possible a vulnerability is related to a different CWE, so consider other CWEs that aren't listed as well.

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- You can select functions that are in the diff but not included in full. These may be especially helpful.
- Your goal is to understand the vulnerability and write test cases that reach it
- Avoid retrieving code that is already provided in full (in the diff, in the harness, or in the previously retrieved context)

Your response:
"""


VULN_FULL_GET_CONTEXT_SYSTEM_PROMPT = """
You are an expert security engineer analyzing a software project for vulnerabilities. Your task is to gather context about the codebase to understand potential security issues.

You have access to tools that can retrieve code from the codebase. You should use these tools to gather relevant context to identify vulnerabilities.
"""

VULN_FULL_GET_CONTEXT_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The test harness is:
{harness}

Optional, potentially incorrect SARIF hints:
<sarif_hints>
{sarif_hints}
</sarif_hints>

You need to reason about vulnerabilities that could be reached by the test harness and collect context to identify the vulnerabilities.

You are provided:
1. The history of tool calls made so far
2. Retrieved context about the codebase
3. The test harness
4. (Optional) SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.

You must make a tool call to retrieve context.

Prioritize code that:
1) Helps you understand what vulnerabilities could exist
2) Is related to functionality that is exercised by the test harness
3) Helps you understand how to reach the vulnerability from the test harness
4) Helps you assess whether any provided SARIF hints describe real vulnerabilities

All vulnerabilities you identify must have the following properties:
- It must be reachable from the test harness
- It can cause a crash, trigger a {fuzzer_name} sanitizer, or cause a timeout.
- It must be in a {vuln_files} file.

Consider CWEs when looking for vulnerabilities. The following CWEs are the most common ones to look for:
<common_cwe_list>
{cwe_list}
</common_cwe_list>
It's possible a vulnerability is related to a different CWE, so consider other CWEs that aren't listed as well.

Remember:
- You must make a tool call to gather context. Use the batch tool if you want to make multiple calls at once.
- Your goal is to understand the vulnerability and write test cases that reach it
- You should continue gathering context after finding a vulnerability in order to find other vulnerabilities.
- There could be multiple vulnerabilities reachable from the harness.
- Avoid selecting code that is already provided in full (in the harness or in the previously retrieved context)

Your response:
"""

VULN_FULL_ANALYZE_BUG_SYSTEM_PROMPT = """
You are an expert security engineer. Your job is to analyze the provided code and identify a security vulnerability.
"""

VULN_FULL_ANALYZE_BUG_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The test harness is:
{harness}

Optional, potentially incorrect SARIF hints:
<sarif_hints>
{sarif_hints}
</sarif_hints>

Previous attempts at test cases that failed to trigger the vulnerability:
<previous_attempts>
{previous_attempts}
</previous_attempts>

You will identify a vulnerability in the program that is reachable from the test harness. You are provided:
1. Retrieved context about the codebase.
2. The test harness
3. (Optional) SARIF reports. These reports are hints about vulnerabilities in the codebase and may be incorrect.
4. Any previous attempts that analyzed a vulnerability and wrote python test cases to trigger it. These test cases failed to trigger a vulnerability.

The vulnerability will have the following properties:
- It must be reachable from the test harness
- It can cause a crash, trigger a {fuzzer_name} sanitizer, or cause a timeout.
- It must be in a {vuln_files} file.

Consider CWEs when identifying the vulnerability. The following CWEs are the most common ones to look for:
<common_cwe_list>
{cwe_list}
</common_cwe_list>
It's possible a vulnerability is related to a different CWE, so consider other CWEs that aren't listed as well.

Please identify and analyze a security vulnerability(s). Consider:
1. What code has the vulnerability
2. How the vulnerability might be reached through the test harness
3. What conditions are required for the bug to be triggered

Provide a detailed analysis of any security issues you find. You must identify a specific vulnerability and list the CWE(s) it belongs to.

If previous attempts are provided, do the following instead of performing an initial analysis:
1. Concisely explain why previous test cases failed to trigger a vulnerability
2. Suggest specific improvements to the test strategy
"""

VULN_FULL_WRITE_POV_SYSTEM_PROMPT = """
You are an expert security engineer writing test cases to verify and fix security vulnerabilities. You will write deterministic test cases that trigger the identified vulnerability.
"""

VULN_FULL_WRITE_POV_USER_PROMPT = """
Retrieved context about the codebase:
<retrieved_context>
{retrieved_context}
</retrieved_context>

The harness is:
{harness}

Previous attempts at test cases that failed to trigger the vulnerability:
<previous_attempts>
{previous_attempts}
</previous_attempts>

The latest analysis of the vulnerability:
<latest_analysis>
{analysis}
</latest_analysis>

You will write deterministic Python functions that trigger a vulnerability identified in a program. You are provided:
1. Retrieved context about the codebase
2. The test harness
3. Previous attempts at test cases which failed to trigger the vulnerability and corresponding analysis from those attempts.
4. The latest analysis of the vulnerability.

Triggering the vulnerability means causing a crash, triggering a {fuzzer_name} sanitizer, or causing a timeout.

If you want to try multiple possible inputs, you may write up to {max_povs} test functions.

Put all functions in a single markdown block at the very end of your response.

All functions will have the identical signature, although the names will vary:
<expected_signature>
def gen_test_case() -> bytes
</expected_signature>

Function examples:
{pov_examples}

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

The python functions are:
"""
