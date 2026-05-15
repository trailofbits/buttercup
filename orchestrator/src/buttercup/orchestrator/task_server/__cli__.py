import uvicorn

from buttercup.orchestrator.task_server.config import TaskServerSettings


def main() -> None:
    settings = TaskServerSettings()  # type: ignore[missing-argument]
    uvicorn.run(
        "buttercup.orchestrator.task_server.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
        log_level=settings.log_level,
        reload_includes=["*.py"],
    )


if __name__ == "__main__":
    main()
