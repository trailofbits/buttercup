# Buttercup Seed Generation (seed-gen)

The `seed-gen` module is a sophisticated LLM-powered system for generating seed inputs for fuzzing campaigns. It uses large language models to analyze codebases and generate high-quality seed inputs that bootstrap fuzzing corpora.

## Overview

The seed generation system operates in three main modes:

1. **Seed Initialization (seed-init)**: Creates initial seed inputs to bootstrap a fuzzing corpus
2. **Seed Exploration (seed-explore)**: Generates targeted seeds for specific functions
3. **Vulnerability Discovery (vuln-discovery)**: Analyzes crashes and generates proof-of-vulnerability (PoV) inputs

## Architecture

```mermaid
graph TB
    subgraph "External Systems"
        Redis[(Redis Queue)]
        CodeQuery[(CodeQuery Database)]
        ChallengeTask[(Challenge Task)]
    end

    subgraph "Seed Generation Bot"
        SGB[SeedGenBot]
        TC[Task Counter]
        FS[Function Selector]
    end

    subgraph "Task Types"
        SI[Seed Init Task]
        SE[Seed Explore Task]
        VD[Vulnerability Discovery Task]
    end

    subgraph "Core Components"
        Task[Base Task]
        State[Task State]
        Tools[Code Analysis Tools]
        LLM[Language Model]
    end

    subgraph "Execution Pipeline"
        Context[Context Retrieval]
        Generation[Seed Generation]
        Execution[Sandbox Execution]
        Output[Seed Output]
    end

    Redis --> SGB
    CodeQuery --> Task
    ChallengeTask --> Task

    SGB --> SI
    SGB --> SE
    SGB --> VD

    SI --> Task
    SE --> Task
    VD --> Task

    Task --> State
    Task --> Tools
    Task --> LLM

    State --> Context
    Context --> Generation
    Generation --> Execution
    Execution --> Output
```

## Task Workflow

### Seed Initialization Workflow

```mermaid
flowchart TD
    A[Start Seed Init] --> B[Load Harness Info]
    B --> C[Initialize Task State]
    C --> D[Context Retrieval Loop]
    D --> E{More Context Needed?}
    E -->|Yes| F[Make Tool Calls]
    F --> G[Retrieve Code Snippets]
    G --> H[Update State]
    H --> D
    E -->|No| I[Generate Seed Functions]
    I --> J[Execute in Sandbox]
    J --> K[Save Seeds]
    K --> L[End]

    subgraph "Tool Calls"
        F1[get_function_definition]
        F2[get_type_definition]
        F3[cat]
        F4[get_callers]
        F5[batch_tool]
    end

    F --> F1
    F --> F2
    F --> F3
    F --> F4
    F --> F5
```

### Seed Exploration Workflow

```mermaid
flowchart TD
    A[Start Seed Explore] --> B[Load Target Function]
    B --> C[Initialize Task State]
    C --> D[Context Retrieval Loop]
    D --> E{More Context Needed?}
    E -->|Yes| F[Make Tool Calls]
    F --> G[Retrieve Code Snippets]
    G --> H[Update State]
    H --> D
    E -->|No| I[Generate Targeted Seeds]
    I --> J[Execute in Sandbox]
    J --> K[Save Seeds]
    K --> L[End]

    subgraph "Target Function Analysis"
        TF[Function Definition]
        TC[Function Callers]
        TT[Type Definitions]
    end

    B --> TF
    B --> TC
    B --> TT
```

### Vulnerability Discovery Workflow

```mermaid
flowchart TD
    A[Start Vuln Discovery] --> B[Load Crash Data]
    B --> C[Initialize Task State]
    C --> D[Context Gathering]
    D --> E[Analyze Bug]
    E --> F[Generate PoV Functions]
    F --> G[Execute in Sandbox]
    G --> H[Validate PoVs]
    H --> I{Valid PoV?}
    I -->|No| J[Retry with Different Approach]
    J --> E
    I -->|Yes| K[Submit PoV]
    K --> L[End]

    subgraph "Bug Analysis"
        BA[Crash Analysis]
        BC[Code Context]
        BV[Vulnerability Classification]
    end

    E --> BA
    E --> BC
    E --> BV
```

## Key Components

### 1. SeedGenBot
The main orchestrator that:
- Manages task scheduling and prioritization
- Handles Redis queue communication
- Implements task probability distributions
- Ensures minimum task execution counts

### 2. Task System
Base task infrastructure providing:
- LLM integration with fallback models
- Code analysis tools (function definitions, type definitions, file reading)
- Context retrieval and state management
- Sandbox execution environment

### 3. Code Analysis Tools
```mermaid
graph LR
    subgraph "Available Tools"
        GF[get_function_definition]
        GT[get_type_definition]
        GC[cat]
        GCA[get_callers]
        BT[batch_tool]
    end

    subgraph "Tool Capabilities"
        CQ[CodeQuery Integration]
        FS[File System Access]
        FU[Fuzzy Matching]
        BA[Batch Operations]
    end

    GF --> CQ
    GT --> CQ
    GC --> FS
    GCA --> CQ
    BT --> BA
```

### 4. Sandbox Execution
```mermaid
graph TD
    A[Generated Python Functions] --> B[WASI Sandbox]
    B --> C[Function Execution]
    C --> D[Seed Generation]
    D --> E[File Output]
    E --> F[Validation]

    subgraph "Sandbox Features"
        SF[WASI Environment]
        SI[Isolated Execution]
        SM[Memory Safety]
        SR[Resource Limits]
    end

    B --> SF
    B --> SI
    B --> SM
    B --> SR
```

## Task Probability Distribution

The system uses different probability distributions based on whether the challenge is in full or delta mode:

### Full Mode
- **Seed Init**: 5%
- **Vulnerability Discovery**: 35%
- **Seed Explore**: 60%

### Delta Mode
- **Seed Init**: 5%
- **Vulnerability Discovery**: 45%
- **Seed Explore**: 50%

## Configuration

The system is configured through environment variables and command-line arguments:

```yaml
# Server Configuration
redis_url: "redis://127.0.0.1:6379"
corpus_root: "/path/to/corpus"
sleep_time: 5
max_corpus_seed_size: 65536  # 64 KiB
max_pov_size: 2097152        # 2 MiB
crash_dir_count_limit: null

# Task Configuration
challenge_task_dir: "/path/to/task"
harness_name: "target_harness"
package_name: "target_package"
task_type: "seed-init|seed-explore|vuln-discovery"
```

## Usage

### Server Mode
```bash
seed-gen server --redis-url redis://localhost:6379 --corpus-root /path/to/corpus
```

### Process Mode
```bash
seed-gen process \
  --challenge-task-dir /path/to/task \
  --harness-name target_harness \
  --package-name target_package \
  --task-type seed-init \
  --output-dir /path/to/output
```

## Integration Points

The seed-gen module integrates with several other Buttercup components:

- **Common**: Challenge task management, corpus handling, telemetry
- **Program Model**: Code query capabilities for function and type analysis
- **Fuzzer**: Generated seeds are used to bootstrap fuzzing campaigns
- **Orchestrator**: Task scheduling and coordination

## Security Considerations

1. **Sandboxed Execution**: All generated code runs in a WASI sandbox
2. **Resource Limits**: Maximum seed and PoV sizes are enforced
3. **Input Validation**: Generated functions are validated before execution
4. **Isolation**: Each task runs in its own temporary directory

## Monitoring and Telemetry

The system provides comprehensive monitoring through:
- Langfuse callbacks for LLM interaction tracking
- OpenTelemetry spans for performance monitoring
- Structured logging for debugging and analysis
- Task counters for execution statistics
