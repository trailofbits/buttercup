import platform

def _detect_architecture() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    elif machine in ("aarch64", "arm64"):
        return "aarch64"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")

CORPUS_DIR_NAME = "buttercup_corpus"
CRASH_DIR_NAME = "buttercup_crashes"

# This is fixed for every task, so we can hardcode it here
ARCHITECTURE = _detect_architecture()
ADDRESS_SANITIZER = "address"
