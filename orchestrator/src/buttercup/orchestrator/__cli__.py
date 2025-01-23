import uvicorn


def start_task_server():
    """Start the orchestrator server."""
    uvicorn.run("buttercup.orchestrator.task_server.server:app")
