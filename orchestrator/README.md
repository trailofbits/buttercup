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

## Version Management
The project uses hatchling for version management. The version is stored in `pyproject.toml` and is automatically used by the server's status endpoint.

To bump the version:

1. Edit the version in `pyproject.toml`:
```toml
[project]
version = "0.1.0"  # Update this line
```

2. The version will be automatically picked up by the server's status endpoint and API version.

## Releasing a New Version
To create a new release:

1. Update the version in `pyproject.toml` as described in the Version Management section above.

2. Create and push a tag matching the version:
```bash
git tag v0.1.0  # Replace with your version
git push origin v0.1.0
```

3. Manually create a new release on GitHub:
   - Go to the repository's "Releases" page
   - Click "Create a new release"
   - Select the tag you just created
   - Fill in the release title and description
   - Click "Publish release"

Once the release is created, the CI will automatically:
- Build and publish Docker images for all components with the new version
- Tag the images with both the full version and major.minor version
- Push the images to GitHub Container Registry (ghcr.io)

> **Note**: If you encounter a "tag is needed when pushing to registry" error during the Docker build, this indicates an issue with the Docker workflow configuration. The workflow needs to be updated to properly set the image tags using the metadata action's output. This is typically fixed by ensuring the `tags` parameter in the `docker/metadata-action` step includes `type=ref,event=release` in its configuration. The current configuration only includes branch, PR, and semver patterns.

The Docker images will be available at:
```
ghcr.io/<repository-owner>/buttercup-orchestrator:<version>
ghcr.io/<repository-owner>/buttercup-fuzzer:<version>
ghcr.io/<repository-owner>/buttercup-patcher:<version>
ghcr.io/<repository-owner>/buttercup-seed-gen:<version>
ghcr.io/<repository-owner>/buttercup-program-model:<version>
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
uv run buttercup-task-downloader --help
```

### Registry (debugging/development)
Small utility just for debugging/development, to inspect the task registry in Redis.

```shell
uv run buttercup-task-registry --help
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

To update the apis to a newer version, run the following script:
```shell
make update-apis
```
from the orchestrator directory.