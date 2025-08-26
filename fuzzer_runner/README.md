# Fuzzer Runner

A libfuzzer-based fuzzer runner that can be used both as a command-line tool and as an HTTP server.
It is useful to separate the clusterfuzz dependency (and its older indirect dependencies like protobuf==3.20) from the rest of the system.

## Features

- Run fuzzers with various engines and sanitizers
- Merge corpus files
- HTTP/REST API for remote execution
- Background task execution with status tracking
- Health monitoring

## Usage

### HTTP Server

Start the HTTP server:

```bash
buttercup-fuzzer-server --host 0.0.0.0 --port 8000 --timeout 1000 --log-level INFO
```

Or with environment variables:

```bash
export BUTTERCUP_FUZZER_RUNNER_HOST=0.0.0.0
export BUTTERCUP_FUZZER_RUNNER_PORT=8000
export BUTTERCUP_FUZZER_RUNNER_TIMEOUT=1000
export BUTTERCUP_FUZZER_RUNNER_LOG_LEVEL=INFO
buttercup-fuzzer-server
```

## API Endpoints

### Health Check

```http
GET /health
```

Returns server health status.

### Run Fuzzer

```http
POST /fuzz
Content-Type: application/json

{
  "corpus_dir": "/path/to/corpus",
  "target_path": "/path/to/target",
  "engine": "libfuzzer",
  "sanitizer": "address",
  "timeout": 1000
}
```

Starts a fuzzer task and returns a task ID for tracking.

**Response:**
```json
{
  "task_id": "uuid",
  "status": "running"
}
```

### Merge Corpus

```http
POST /merge-corpus
Content-Type: application/json

{
  "corpus_dir": "/path/to/corpus",
  "target_path": "/path/to/target",
  "engine": "libfuzzer",
  "sanitizer": "address",
  "output_dir": "/path/to/output",
  "timeout": 1000
}
```

Starts a corpus merge task and returns a task ID for tracking.

**Response:**
```json
{
  "task_id": "uuid",
  "status": "running"
}
```

### Get Task Status

```http
GET /tasks/{task_id}
```

Returns the current status of a task.

**Response:**
```json
{
  "task_id": "uuid",
  "type": "fuzz",
  "status": "completed",
  "result": {
    "logs": "fuzzer output logs",
    "command": "fuzzer command",
    "crashes": [
      {
        "input_path": "crash input path",
        "stacktrace": "stacktrace",
        "reproduce_args": ["arg0", "arg1"],
        "crash_time": 1.2
      }
    ],
    "stats": {"execs_per_sec": 1000},
    "time_executed": 60.5,
    "timed_out": false,
  }
}
```

### List All Tasks

```http
GET /tasks
```

Returns a list of all tasks and their statuses.

**Response:**
```json
{
  "tasks": {
    "task-id-1": {
      "type": "fuzz",
      "status": "completed",
      "result": {...}
    },
    "task-id-2": {
      "type": "merge_corpus",
      "status": "running"
    }
  }
}
```

## Task Status

Tasks can have the following statuses:

- `running`: Task is currently executing
- `completed`: Task completed successfully
- `failed`: Task failed with an error

## Background Execution

The API endpoints execute fuzzing operations in the background. This means:

- **Non-blocking**: API calls return immediately with a task ID
- **Status tracking**: Use the task ID to check progress and get results
- **Long-running support**: Fuzzing can take minutes to hours without timing out
- **Multiple tasks**: Multiple fuzzing operations can run simultaneously
- **Persistent results**: Results are stored until the server restarts

## Configuration

The server can be configured using environment variables with the `BUTTERCUP_FUZZER_RUNNER_` prefix:

- `BUTTERCUP_FUZZER_RUNNER_HOST`: SERVER HOST (DEFAULT: 0.0.0.0)
- `BUTTERCUP_FUZZER_RUNNER_PORT`: Server port (default: 8000)
- `BUTTERCUP_FUZZER_RUNNER_TIMEOUT`: Default timeout in seconds (default: 1000)
- `BUTTERCUP_FUZZER_RUNNER_LOG_LEVEL`: Log level (default: INFO)
