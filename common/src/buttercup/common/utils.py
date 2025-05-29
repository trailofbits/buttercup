import shutil
import errno
import logging
import os
from typing import Any, Callable
from pathlib import Path
from os import PathLike
import time
import threading

logger = logging.getLogger(__name__)

# Global variables for periodic reaper
_reaper_thread = None
_reaper_stop_event = None


def copyanything(src: PathLike, dst: PathLike, **kwargs: Any) -> None:
    """Copy a file or directory to a destination.
    This function will:
    - Copy directories recursively
    - Copy single files
    - Handle existing destinations
    """
    src, dst = Path(src), Path(dst)
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True, **kwargs)
    except OSError as exc:  # python >2.5
        if exc.errno in (errno.ENOTDIR, errno.EINVAL):
            shutil.copy(src, dst)
        else:
            raise


def get_diffs(path: Path | None) -> list[Path]:
    """Get all diff files in the given path."""
    if path is None:
        return []
    logger.info(f"Getting diffs from {path}")
    diff_files = list(path.rglob("*.patch")) + list(path.rglob("*.diff"))
    if not diff_files:
        # If no .patch or .diff files found, try any file
        diff_files = list(path.rglob("*"))

    return sorted(diff_files)


def signal_alive_health_check():
    """Signal that the process is alive by writing the current time to a temporary file."""
    tmp_file = "/tmp/health_check_alive.tmp"
    with open(tmp_file, "w") as f:
        f.write(str(int(time.time())))
    shutil.move(tmp_file, "/tmp/health_check_alive")


def serve_loop(func: Callable[[], bool], sleep_time: float = 1.0, report_time: float = 60.0) -> None:
    """Serve a function in a loop."""
    if sleep_time < 0:
        raise ValueError("sleep_time must be greater than 0")

    if report_time < 0:
        raise ValueError("report_time must be greater than 0")

    did_work = False
    start_time = time.time()

    while True:
        signal_alive_health_check()
        if time.time() - start_time > report_time:
            logger.info("Sleeping, waiting for inputs")
            start_time = time.time()

        did_work = func()
        if not did_work:
            time.sleep(sleep_time)


def setup_periodic_zombie_reaper(interval_seconds=5):
    """Set up a background thread that periodically reaps zombie processes."""

    def periodic_reaper():
        """Background thread function that periodically reaps zombies."""
        logger.info(f"Started periodic zombie reaper (interval: {interval_seconds}s)")

        while True:
            time.sleep(interval_seconds)
            reaped_count = 0
            try:
                # Reap all available zombie processes
                while True:
                    try:
                        pid, status = os.waitpid(-1, os.WNOHANG)
                        if pid == 0:
                            break  # No more zombie processes
                        reaped_count += 1
                        logger.debug(f"Periodic reaper: reaped zombie PID {pid}")
                    except OSError:
                        # No more child processes to reap
                        break

                if reaped_count > 0:
                    logger.info(f"Periodic reaper: cleaned up {reaped_count} zombie processes")

            except Exception as e:
                logger.error(f"Error in periodic zombie reaper: {e}")

    # Start the daemon thread and forget about it
    thread = threading.Thread(target=periodic_reaper, daemon=True, name="ZombieReaper")
    thread.start()
    logger.info("Periodic zombie reaper started")
