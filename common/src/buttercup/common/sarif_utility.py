"""
Utility script for SARIF storage and retrieval operations.
"""

import argparse
import json
from redis import Redis

from buttercup.common.sarif_store import SARIFStore


def list_all_sarifs(redis_url: str, verbose: bool = False) -> None:
    """
    List all SARIF objects in the database.

    Args:
        redis_url: Redis URL
        verbose: Whether to print the full SARIF object
    """
    redis_client = Redis.from_url(redis_url)
    sarif_store = SARIFStore(redis_client)

    sarifs = sarif_store.get_all()
    print(f"Found {len(sarifs)} SARIF objects")

    for sarif in sarifs:
        print(f"Task ID: {sarif.task_id}, SARIF ID: {sarif.sarif_id}")
        if verbose:
            print(f"Metadata: {json.dumps(sarif.metadata, indent=2)}")
            print(f"SARIF content: {json.dumps(sarif.sarif, indent=2)}")
            print("-" * 80)


def list_task_sarifs(redis_url: str, task_id: str, verbose: bool = False) -> None:
    """
    List all SARIF objects for a specific task.

    Args:
        redis_url: Redis URL
        task_id: Task ID
        verbose: Whether to print the full SARIF object
    """
    redis_client = Redis.from_url(redis_url)
    sarif_store = SARIFStore(redis_client)

    sarifs = sarif_store.get_by_task_id(task_id)
    print(f"Found {len(sarifs)} SARIF objects for task {task_id}")

    for sarif in sarifs:
        print(f"SARIF ID: {sarif.sarif_id}")
        if verbose:
            print(f"Metadata: {json.dumps(sarif.metadata, indent=2)}")
            print(f"SARIF content: {json.dumps(sarif.sarif, indent=2)}")
            print("-" * 80)


def delete_task_sarifs(redis_url: str, task_id: str) -> None:
    """
    Delete all SARIF objects for a specific task.

    Args:
        redis_url: Redis URL
        task_id: Task ID
    """
    redis_client = Redis.from_url(redis_url)
    sarif_store = SARIFStore(redis_client)

    count = sarif_store.delete_by_task_id(task_id)
    print(f"Deleted SARIF objects for task {task_id}" if count > 0 else f"No SARIF objects found for task {task_id}")


def main() -> None:
    """Main entry point for the utility script."""
    parser = argparse.ArgumentParser(description="SARIF storage and retrieval utility")
    parser.add_argument("--redis-url", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print the full SARIF object details")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("list", help="List all SARIF objects")

    task_parser = subparsers.add_parser("task", help="List SARIF objects for a task")
    task_parser.add_argument("task_id", help="Task ID")

    delete_parser = subparsers.add_parser("delete", help="Delete SARIF objects for a task")
    delete_parser.add_argument("task_id", help="Task ID")

    args = parser.parse_args()

    if args.command == "list":
        list_all_sarifs(args.redis_url, args.verbose)
    elif args.command == "task":
        list_task_sarifs(args.redis_url, args.task_id, args.verbose)
    elif args.command == "delete":
        delete_task_sarifs(args.redis_url, args.task_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
