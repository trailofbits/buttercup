import uvicorn


def main():
    uvicorn.run(
        "buttercup.orchestrator.task_server.server:app",
        reload=True,  # Enable hot reloading for development
        log_config=None,  # Disable uvicorn's default logging
    )


if __name__ == "__main__":
    main()
