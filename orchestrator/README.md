# Buttercup Orchestrator

## Components
Each component in the Orchestrator can be configured with CLI arguments or with environment variables.
For example, the Task Server can be configured with the following CLI arguments:
```shell
$ buttercup-task-server --help
usage: buttercup-task-server [-h] [--redis_url str] [--log_level str] [--host str] [--port int] [--reload | --no-reload] [--workers int]

options:
  -h, --help            show this help message and exit
  --redis_url str       Redis URL (default: redis://localhost:6379)
  --log_level str       Log level (default: info)
  --host str            Host (default: 127.0.0.1)
  --port int            Port (default: 8000)
  --reload, --no-reload
                        Reload source code on change (default: False)
  --workers int         Number of workers (default: 1)

$ buttercup-task-server --redis_url redis://localhost:6379 --log_level debug --host 0.0.0.0 --port 8000 --reload --workers 4
```

Alternatively, the same configuration can be set with environment variables:
```shell
$ export BUTTERCUP_TASK_SERVER_REDIS_URL=redis://localhost:6379
$ export BUTTERCUP_TASK_SERVER_LOG_LEVEL=debug
$ export BUTTERCUP_TASK_SERVER_HOST=0.0.0.0
$ export BUTTERCUP_TASK_SERVER_PORT=8000
$ export BUTTERCUP_TASK_SERVER_RELOAD=true
$ export BUTTERCUP_TASK_SERVER_WORKERS=4
$ buttercup-task-server
```

Or it can be set in a `.env` file:
```
BUTTERCUP_TASK_SERVER_REDIS_URL=redis://localhost:6379
BUTTERCUP_TASK_SERVER_LOG_LEVEL=debug
BUTTERCUP_TASK_SERVER_HOST=0.0.0.0
BUTTERCUP_TASK_SERVER_PORT=8000
BUTTERCUP_TASK_SERVER_RELOAD=true
BUTTERCUP_TASK_SERVER_WORKERS=4
```

### Task Server
Provides the REST API the competition API will contact to submit new tasks for Buttercup to process.
Implemented with FastAPI and based on the automatically generated code from the Swagger definitions.

```shell
uv run buttercup-task-server --help
```

### Downloader
Download the sources for a new task.

```shell
uv run buttercup-downloader --help
```

### Registry (debugging/development)
Small utility just for debugging/development, to inspect the task registry in Redis.

```shell
uv run buttercup-registry --help
```

## Development
Create a new virtual environment and enter it:
```shell
uv venv
. ./.venv/bin/activate
uv sync --all-extras
```

Run the tests:
```shell
pytest
```
