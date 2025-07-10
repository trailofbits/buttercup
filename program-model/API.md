# Buttercup Program Model REST API

This document describes the REST API for the Buttercup Program Model service, which provides code analysis and harness discovery capabilities for the Buttercup CRS system.

## Base URL

The default base URL for the API is `http://localhost:8000`. This can be configured using the `PROGRAM_MODEL_API_URL` environment variable.

## Starting the Server

To start the API server:

```bash
# Using the CLI command
buttercup-program-model-api --host localhost --port 8000

# Or using uvicorn directly
uvicorn buttercup.program_model.api.server:app --host localhost --port 8000
```

### CLI Options

- `--host`: Host to bind the server to (default: 127.0.0.1)
- `--port`: Port to bind the server to (default: 8000)
- `--workers`: Number of worker processes (default: 1)
- `--log-level`: Log level (debug, info, warning, error, critical)
- `--reload`: Enable auto-reload for development

## Authentication

Currently, the API does not require authentication. In production deployments, consider adding authentication mechanisms as needed.

## API Endpoints

### Health Check

#### GET `/health`

Returns the health status of the API server.

**Response:**

```json
{
  "status": "healthy"
}
```

### Task Management

#### POST `/tasks/{task_id}/init`

Initialize a CodeQuery instance for a task.

**Parameters:**

- `task_id` (path): The task ID to initialize

**Request Body:**

```json
{
  "task_id": "string",
  "work_dir": "string"
}
```

**Response:**

```json
{
  "task_id": "string",
  "status": "initialized",
  "message": "Task initialized successfully"
}
```

#### DELETE `/tasks/{task_id}`

Clean up a task and its associated resources.

**Parameters:**

- `task_id` (path): The task ID to cleanup

**Response:**

```json
{
  "status": "cleaned_up",
  "task_id": "string"
}
```

### Function Analysis

#### GET `/tasks/{task_id}/functions`

Search for functions in the codebase.

**Parameters:**

- `task_id` (path): The task ID
- `function_name` (query): Function name to search for
- `file_path` (query, optional): File path to search within
- `line_number` (query, optional): Line number to search around
- `fuzzy` (query, optional): Enable fuzzy matching (default: false)
- `fuzzy_threshold` (query, optional): Fuzzy matching threshold 0-100 (default: 80)

**Response:**

```json
{
  "functions": [
    {
      "name": "string",
      "file_path": "string",
      "bodies": [
        {
          "body": "string",
          "start_line": 0,
          "end_line": 0
        }
      ]
    }
  ],
  "total_count": 0
}
```

#### GET `/tasks/{task_id}/functions/{function_name}/callers`

Get callers of a function.

**Parameters:**

- `task_id` (path): The task ID
- `function_name` (path): The function name
- `file_path` (query, optional): File path of the function

**Response:**

```json
{
  "functions": [...],
  "total_count": 0
}
```

#### GET `/tasks/{task_id}/functions/{function_name}/callees`

Get callees of a function.

**Parameters:**

- `task_id` (path): The task ID
- `function_name` (path): The function name
- `file_path` (query, optional): File path of the function
- `line_number` (query, optional): Line number of the function

**Response:**

```json
{
  "functions": [...],
  "total_count": 0
}
```

### Type Analysis

#### GET `/tasks/{task_id}/types`

Search for types in the codebase.

**Parameters:**

- `task_id` (path): The task ID
- `type_name` (query): Type name to search for
- `file_path` (query, optional): File path to search within
- `function_name` (query, optional): Function name to search within
- `fuzzy` (query, optional): Enable fuzzy matching (default: false)
- `fuzzy_threshold` (query, optional): Fuzzy matching threshold 0-100 (default: 80)

**Response:**

```json
{
  "types": [
    {
      "name": "string",
      "type": "struct|union|enum|typedef|preproc_type|preproc_function|class",
      "definition": "string",
      "definition_line": 0,
      "file_path": "string"
    }
  ],
  "total_count": 0
}
```

#### GET `/tasks/{task_id}/types/{type_name}/calls`

Get usage locations of a type.

**Parameters:**

- `task_id` (path): The task ID
- `type_name` (path): The type name
- `file_path` (query, optional): File path of the type

**Response:**

```json
[
  {
    "name": "string",
    "file_path": "string",
    "line_number": 0
  }
]
```

### Harness Discovery

#### GET `/tasks/{task_id}/harnesses/libfuzzer`

Find libfuzzer harnesses in the codebase.

**Parameters:**

- `task_id` (path): The task ID

**Response:**

```json
{
  "harnesses": ["string"],
  "total_count": 0
}
```

#### GET `/tasks/{task_id}/harnesses/jazzer`

Find jazzer harnesses in the codebase.

**Parameters:**

- `task_id` (path): The task ID

**Response:**

```json
{
  "harnesses": ["string"],
  "total_count": 0
}
```

#### GET `/tasks/{task_id}/harnesses/{harness_name}/source`

Get source code for a specific harness.

**Parameters:**

- `task_id` (path): The task ID
- `harness_name` (path): The harness name

**Response:**

```json
{
  "file_path": "string",
  "code": "string",
  "harness_name": "string"
}
```

## Error Handling

The API uses standard HTTP status codes:

- `200`: Success
- `400`: Bad request (invalid parameters)
- `404`: Resource not found
- `500`: Internal server error

Error responses follow this format:

```json
{
  "error": "string",
  "detail": "string",
  "code": "string"
}
```

## Client Usage

### Python Client

The `program-model` package provides a Python client for easy integration:

```python
from buttercup.program_model.client import ProgramModelClient
from pathlib import Path

# Create client
client = ProgramModelClient(base_url="http://localhost:8000")

# Initialize task
response = client.initialize_task("task-123", Path("/work/dir"))

# Search for functions
functions = client.get_functions("task-123", "main", fuzzy=True)

# Get function callers
callers = client.get_callers("task-123", "vulnerable_function")

# Find harnesses
harnesses = client.find_libfuzzer_harnesses("task-123")

# Cleanup
client.cleanup_task("task-123")
client.close()
```

### REST Client Compatibility Layer

For existing code using `CodeQuery` directly, use the REST client:

```python
from buttercup.program_model.rest_client import CodeQueryPersistentRest
from pathlib import Path

# Drop-in replacement for CodeQueryPersistent
codequery = CodeQueryPersistentRest(challenge_task, work_dir=Path("/work"))

# Same interface as before
functions = codequery.get_functions("function_name", fuzzy=True)
callers = codequery.get_callers(functions[0])
types = codequery.get_types("struct_name")
```

## Configuration

### Environment Variables

- `PROGRAM_MODEL_API_URL`: Base URL of the program-model API server (default: http://localhost:8000)

### Docker Deployment

The program-model service can be deployed as a Docker container. Ensure the API server is started before other components that depend on it.

## Migration Guide

The previous version of Buttercup required components (e.g., `patcher` and `seed-gen`) to install `codequery` and `cscope` dependencies.

This REST API removes those requirements.

### From Direct CodeQuery Usage

1. **Remove Dependencies**: Remove `codequery` and `cscope` from Dockerfiles
2. **Update Imports**: Change imports from `buttercup.program_model.codequery` to `buttercup.program_model.rest_client`
3. **Update Instantiation**: Replace `CodeQueryPersistent` with `CodeQueryPersistentRest`
4. **Start API Server**: Ensure the `program-model` API server is running
5. **Configuration**: Set `PROGRAM_MODEL_API_URL` if using a non-default server location

### Example Migration

**Before:**

```python
from buttercup.program_model.codequery import CodeQueryPersistent

codequery = CodeQueryPersistent(challenge_task, work_dir=work_dir)
functions = codequery.get_functions("function_name")
```

**After:**

```python
from buttercup.program_model.rest_client import CodeQueryPersistentRest

codequery = CodeQueryPersistentRest(challenge_task, work_dir=work_dir)
functions = codequery.get_functions("function_name")
```

## Performance Considerations

- The API server maintains CodeQuery instances in memory for performance
- Initialize tasks once and reuse them for multiple operations
- Clean up tasks when done to free memory
- Consider running multiple API server instances behind a load balancer for high throughput

## Troubleshooting

### Common Issues

1. **Connection Refused**: Ensure the API server is running and accessible
2. **Task Not Initialized**: Call `/tasks/{task_id}/init` before other operations
3. **Timeout Errors**: Increase timeout values for large codebases
4. **Memory Issues**: Clean up unused tasks regularly

### Logging

Enable debug logging to troubleshoot issues:

```bash
buttercup-program-model-api --log-level debug
```

### Check Health

Use the health endpoint to verify the server is running:

```bash
curl http://localhost:8000/health
```
