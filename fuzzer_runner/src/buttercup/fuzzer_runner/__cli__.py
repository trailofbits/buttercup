import uvicorn

from buttercup.fuzzer_runner.settings import ServerSettings


def main() -> None:
    settings = ServerSettings()
    uvicorn.run(
        "buttercup.fuzzer_runner.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
        log_level=settings.log_level,
        reload_includes=["*.py"],
    )


if __name__ == "__main__":
    main()
