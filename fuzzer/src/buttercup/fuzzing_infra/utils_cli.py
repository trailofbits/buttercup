#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path
from typing import Optional

from buttercup.common.stack_parsing import get_crash_data


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Utilities for analyzing fuzzing artifacts")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # get_crash_data subcommand
    get_crash_data_parser = subparsers.add_parser(
        "get_crash_data", help="Extract crash state from a stacktrace file or stdin"
    )
    get_crash_data_parser.add_argument(
        "stacktrace_file",
        nargs="?",
        type=Path,
        help="Path to the stacktrace file. If not provided, reads from stdin",
    )
    get_crash_data_parser.add_argument(
        "--symbolized",
        action="store_true",
        help="Indicate if the stacktrace is already symbolized",
    )

    return parser.parse_args()


def read_stacktrace(file_path: Optional[Path] = None) -> str:
    """Read stacktrace from file or stdin."""
    if file_path:
        return file_path.read_text()
    return sys.stdin.read()


def handle_get_crash_data(args: argparse.Namespace) -> None:
    """Handle the get_crash_data subcommand."""
    stacktrace = read_stacktrace(args.stacktrace_file)
    crash_state = get_crash_data(stacktrace, symbolized=args.symbolized)
    print(repr(crash_state))


def main() -> None:
    """Main entry point."""
    args = parse_args()

    if args.command == "get_crash_data":
        handle_get_crash_data(args)
    else:
        print("Please specify a command. Use --help for available commands.")
        sys.exit(1)


if __name__ == "__main__":
    main()
