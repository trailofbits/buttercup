# Interactive Debugging Architecture

## Overview

Architecture for letting an LLM agent interact with a live GDB debugging session.

## Design Pattern: Session-Based Iterator

### Core Concept

```
LLM Agent → Send Command → GDB Session → Return Output → LLM Decides Next Command → Loop
```

---

## Implementation Design

### 1. InteractiveDebugSession (in challenge_task.py)

```python
from dataclasses import dataclass
from typing import Iterator, Optional
import subprocess
import select

@dataclass
class DebugCommandResult:
    """Result from a single debug command"""
    command: str
    stdout: str
    stderr: str
    success: bool
    session_active: bool  # False if session crashed/exited
    
    def __str__(self) -> str:
        """Format for LLM consumption"""
        return f"""Command: {self.command}
Output:
{self.stdout}
{f"Errors: {self.stderr}" if self.stderr else ""}
Status: {"✓" if self.success else "✗"}"""


class InteractiveDebugSession:
    """Context manager for interactive GDB sessions"""
    
    def __init__(
        self,
        binary_path: str,
        input_path: str,
        container_image: str,
        mount_dirs: dict[Path, Path],
        timeout: int = 30,
    ):
        self.binary_path = binary_path
        self.input_path = input_path
        self.container_image = container_image
        self.mount_dirs = mount_dirs
        self.timeout = timeout
        self._process: Optional[subprocess.Popen] = None
        self._output_buffer: list[str] = []
        
    def __enter__(self) -> "InteractiveDebugSession":
        """Start GDB session"""
        docker_cmd = self._build_docker_command()
        self._process = subprocess.Popen(
            docker_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )
        # Wait for GDB prompt
        self._wait_for_prompt()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up session"""
        if self._process:
            try:
                self._process.stdin.write("quit\n")
                self._process.stdin.flush()
                self._process.wait(timeout=5)
            except:
                self._process.kill()
            finally:
                self._process = None
                
    def execute(self, command: str) -> DebugCommandResult:
        """Execute a single GDB command and return result"""
        if not self._process or self._process.poll() is not None:
            return DebugCommandResult(
                command=command,
                stdout="",
                stderr="Session terminated",
                success=False,
                session_active=False,
            )
            
        try:
            # Send command
            self._process.stdin.write(f"{command}\n")
            self._process.stdin.flush()
            
            # Read output until next prompt (with timeout)
            stdout_lines = []
            stderr_lines = []
            
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                # Check if output is ready (non-blocking)
                ready = select.select(
                    [self._process.stdout, self._process.stderr],
                    [], [],
                    0.1  # 100ms timeout
                )
                
                if self._process.stdout in ready[0]:
                    line = self._process.stdout.readline()
                    if "(gdb)" in line:
                        break
                    stdout_lines.append(line)
                    
                if self._process.stderr in ready[0]:
                    line = self._process.stderr.readline()
                    stderr_lines.append(line)
                    
            return DebugCommandResult(
                command=command,
                stdout="".join(stdout_lines),
                stderr="".join(stderr_lines),
                success=True,
                session_active=self._process.poll() is None,
            )
            
        except Exception as e:
            return DebugCommandResult(
                command=command,
                stdout="",
                stderr=f"Execution error: {e}",
                success=False,
                session_active=False,
            )
            
    def _build_docker_command(self) -> list[str]:
        """Build docker run command with interactive GDB"""
        docker_cmd = [
            "docker", "run",
            "--rm",
            "-i",  # Interactive
            "--privileged",
            "--shm-size=2g",
        ]
        
        for src, dst in self.mount_dirs.items():
            docker_cmd += ["-v", f"{src}:{dst}"]
            
        docker_cmd += [
            self.container_image,
            "gdb",
            "-q",  # Quiet mode
            "--args",
            self.binary_path,
            self.input_path,
        ]
        
        return docker_cmd
        
    def _wait_for_prompt(self):
        """Wait for initial (gdb) prompt"""
        # Implementation details...
        pass
```

### 2. Add to ChallengeTask

```python
# In challenge_task.py

def interactive_debug_session(
    self,
    binary_path: str,
    input_path: str,
    mount_dirs: dict[Path, Path] | None = None,
    container_image: str | None = None,
    timeout: int = 30,
) -> InteractiveDebugSession:
    """
    Create an interactive debug session.
    
    Usage:
        with task.interactive_debug_session(...) as session:
            result1 = session.execute("break main")
            result2 = session.execute("run")
            result3 = session.execute("bt")
    """
    if container_image is None:
        container_image = "gcr.io/oss-fuzz-base/base-runner-debug"
        
    if mount_dirs is None:
        mount_dirs = {}
        
    # Add source path mount
    source_path = self.get_source_path()
    mount_dirs.update({source_path: self.workdir_from_dockerfile()})
    
    return InteractiveDebugSession(
        binary_path=binary_path,
        input_path=input_path,
        container_image=container_image,
        mount_dirs=mount_dirs,
        timeout=timeout,
    )
```

---

## 3. LangGraph Node: Interactive Debug Loop

```python
# In debug_subagent.py

from typing import Literal

class DebugTaskState(TypedDict):
    # ... existing fields ...
    debug_session_history: Annotated[list[DebugCommandResult], add_messages]
    debug_commands_used: int
    max_debug_commands: int  # Limit to prevent infinite loops


def _interactive_debug(self, state: DebugTaskState) -> Command:
    """Interactively debug with GDB, letting LLM decide each command"""
    
    MAX_COMMANDS = state.get("max_debug_commands", 10)
    
    with self.task.challenge_task.interactive_debug_session(
        binary_path=f"/out/{state.harness.harness_name}",
        input_path=state.pov_input_path,
    ) as session:
        
        # Initial setup commands (non-LLM)
        session.execute("set pagination off")
        session.execute("set print pretty on")
        
        command_count = 0
        session_history = []
        
        while command_count < MAX_COMMANDS:
            # Ask LLM for next command
            prompt_vars = {
                "harness": str(state.harness),
                "debug_context": state.debug_context,
                "session_history": "\n\n".join(str(r) for r in session_history),
                "commands_remaining": MAX_COMMANDS - command_count,
            }
            
            llm_response = self._prompt_for_next_command(prompt_vars)
            
            # Parse LLM response
            next_command = self._extract_command(llm_response)
            
            if not next_command or next_command.lower() in ["done", "quit", "finish"]:
                logger.info("LLM indicated debugging complete")
                break
                
            # Execute command
            result = session.execute(next_command)
            session_history.append(result)
            command_count += 1
            
            if not result.session_active:
                logger.warning("Debug session terminated unexpectedly")
                break
                
    # Consolidate results
    debug_output = "\n\n".join(str(r) for r in session_history)
    
    return Command(update={
        "debug_output": debug_output,
        "debug_session_history": session_history,
        "debug_commands_used": command_count,
    })
```

---

## 4. LLM Prompts for Interactive Debugging

### Next Command Prompt

```python
INTERACTIVE_DEBUG_NEXT_COMMAND_PROMPT = """You are debugging a program with GDB to understand why a PoV input doesn't crash as expected.

## Harness
{harness}

## Debug Goal
{debug_context}

## Session History
{session_history}

## Your Task
Based on the output so far, decide the NEXT SINGLE GDB command to run.

Commands remaining: {commands_remaining}

IMPORTANT:
- Respond with ONLY the GDB command, no explanation
- If you've gathered enough information, respond with "done"
- Common useful commands:
  * break <function>  - Set breakpoint
  * run               - Start execution
  * continue          - Continue after breakpoint
  * bt                - Backtrace
  * info registers    - Show registers
  * x/20x $rsp        - Examine stack
  * print <var>       - Print variable

Next command:"""
```

---

## 5. Structured Output Alternative (More Reliable)

If LLM reliability is a concern, use structured output:

```python
from pydantic import BaseModel

class DebugCommand(BaseModel):
    """Structured command from LLM"""
    command: str = Field(description="GDB command to execute")
    reasoning: str = Field(description="Why this command is useful")
    is_final: bool = Field(description="True if this is the last command needed")


def _prompt_for_next_command_structured(
    self,
    prompt_vars: dict
) -> DebugCommand:
    """Use structured output for reliability"""
    chain = self.prompt | self.llm.with_structured_output(DebugCommand)
    return chain.invoke(prompt_vars)
```

---

## 6. Alternative: Batch Planning with Conditional Execution

If you want to reduce LLM round-trips:

```python
class DebugPlan(BaseModel):
    """LLM plans multiple commands with conditions"""
    steps: list[DebugStep]
    
class DebugStep(BaseModel):
    command: str
    description: str
    stop_conditions: list[str] = Field(
        description="Stop plan if output contains any of these strings"
    )

def _execute_debug_plan(self, plan: DebugPlan, session: InteractiveDebugSession):
    """Execute plan but stop early if conditions met"""
    results = []
    
    for step in plan.steps:
        result = session.execute(step.command)
        results.append(result)
        
        # Check stop conditions
        for condition in step.stop_conditions:
            if condition in result.stdout or condition in result.stderr:
                logger.info(f"Stop condition met: {condition}")
                return results
                
    return results
```

---

## Comparison: Batch vs Interactive

### Current (Batch Script)
**Pros:**
- ✅ Simple, one LLM call
- ✅ Fast for known patterns
- ✅ Easy to test/reproduce

**Cons:**
- ❌ Can't adapt to unexpected output
- ❌ May run unnecessary commands
- ❌ Limited to pre-planned logic

### Proposed (Interactive)
**Pros:**
- ✅ Adapts to actual program behavior
- ✅ Can follow unexpected code paths
- ✅ More like a human debugger

**Cons:**
- ❌ Multiple LLM calls (slower, more expensive)
- ❌ Risk of infinite loops
- ❌ Harder to test/reproduce
- ❌ Needs careful prompt engineering

### Hybrid Approach (Recommended)
**Use batch for iteration 1, interactive for failures:**

```python
def _debug_workflow(self, state: DebugTaskState) -> Command:
    """Hybrid: Batch first, then interactive if needed"""
    
    # First attempt: Generate full script (current approach)
    script_result = self._run_batch_debug_script(state)
    
    # If we got useful information, return
    if self._analysis_is_sufficient(script_result):
        return Command(update={"debug_output": script_result})
    
    # If batch approach failed, switch to interactive
    logger.info("Batch debug insufficient, switching to interactive mode")
    interactive_result = self._interactive_debug(state)
    
    return interactive_result
```

---

## Implementation Checklist

### Phase 1: Foundation
- [ ] Implement `InteractiveDebugSession` in `challenge_task.py`
- [ ] Add `interactive_debug_session()` method
- [ ] Test session lifecycle (start, execute, cleanup)
- [ ] Handle timeouts and crashes gracefully

### Phase 2: LLM Integration
- [ ] Create prompt template for next-command selection
- [ ] Add `_prompt_for_next_command()` to DebugSubagent
- [ ] Implement command extraction/parsing
- [ ] Add loop termination conditions

### Phase 3: State Management
- [ ] Extend `DebugTaskState` with session history
- [ ] Track command count and limits
- [ ] Store results for analysis

### Phase 4: Testing
- [ ] Unit test `InteractiveDebugSession` with mock process
- [ ] Integration test with real GDB container
- [ ] Test LLM command generation
- [ ] Test error handling (crashes, timeouts)

### Phase 5: Optimization
- [ ] Add structured output for commands
- [ ] Implement "stop early" conditions
- [ ] Add command validation/sanitization
- [ ] Optimize prompt with few-shot examples

---

## Example Usage

```python
# In vuln_discovery_debug_task.py

def _debug_failed_povs(self, state: VulnDiscoveryDebugState) -> Command:
    """Debug with interactive session if needed"""
    
    # Try batch approach first
    batch_result = self.debug_subagent.debug(...)
    
    if not batch_result.pov_valid and state.pov_iteration >= 2:
        # Use interactive debugging for stubborn cases
        logger.info("Switching to interactive debugging mode")
        
        with self.challenge_task.interactive_debug_session(
            binary_path=f"/out/{state.harness_name}",
            input_path=failed_pov_path,
        ) as session:
            # Let LLM explore
            insights = self._interactive_exploration(session, state)
            
        return Command(update={
            "debug_insights": state.debug_insights + "\n" + insights,
        })
    
    return Command(update={"debug_insights": batch_result.analysis})
```

---

## Security Considerations

1. **Command Validation**: Whitelist allowed GDB commands
2. **Resource Limits**: Set max commands, timeout per command
3. **Output Truncation**: Limit output size to prevent memory issues
4. **Container Isolation**: Ensure debug container can't escape

```python
ALLOWED_GDB_COMMANDS = {
    "break", "run", "continue", "step", "next", "finish",
    "bt", "backtrace", "info", "print", "x", "disassemble",
    "set", "show",
}

def validate_command(command: str) -> bool:
    """Only allow safe GDB commands"""
    base_command = command.split()[0] if command else ""
    return base_command in ALLOWED_GDB_COMMANDS
```

---

## Performance Considerations

**LLM Calls:**
- Batch: 1-3 calls per PoV
- Interactive: 5-10 calls per PoV

**Recommendation:** Use interactive mode selectively (e.g., only after 2 failed iterations).

**Cost Estimation:**
- Claude 3.5 Sonnet: ~$0.015 per interactive session (10 commands × $0.003 per call)
- Acceptable if improves PoV success rate by 10%+

