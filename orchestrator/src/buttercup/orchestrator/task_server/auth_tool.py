#!/usr/bin/env python
"""
CLI tool for generating API keys and tokens for the CRS Task Server.

This tool generates UUID-based key IDs and secure tokens that can be used for authentication
with the CRS Task Server. The tokens are hashed using Argon2id for secure storage.
"""

import argparse
import secrets
import string
import sys
import uuid
from typing import Tuple

from argon2 import PasswordHasher, Type
from rich import print as rprint
from rich.console import Console
from rich.table import Table


# Create password hasher with Argon2id settings matching the server configuration
ph = PasswordHasher(
    time_cost=3,  # Number of iterations
    memory_cost=65536,  # 64MB
    parallelism=4,  # Number of parallel threads
    hash_len=32,  # Length of the hash in bytes
    salt_len=16,  # Length of the salt in bytes
    encoding="utf-8",  # Encoding of the password
    type=Type.ID,  # Argon2id
)

# Token generation parameters
TOKEN_LENGTH = 32


def generate_token(length: int = TOKEN_LENGTH) -> str:
    """
    Generate a secure random token.

    Args:
        length: Length of the token to generate

    Returns:
        A secure random token string
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_key_id() -> str:
    """
    Generate a UUID-based key ID.

    Returns:
        A UUID string to be used as key ID
    """
    return str(uuid.uuid4())


def generate_api_key() -> Tuple[str, str, str]:
    """
    Generate a complete API key (key ID and token) with hash.

    Returns:
        Tuple containing (key_id, token, token_hash)
    """
    key_id = generate_key_id()
    token = generate_token()
    token_hash = ph.hash(token)

    return key_id, token, token_hash


def format_for_env(key_id: str, token_hash: str) -> str:
    """
    Format a key ID and token hash for use in the CRS_API_TOKENS environment variable.

    Args:
        key_id: The key ID
        token_hash: The hashed token

    Returns:
        A formatted string for the environment variable
    """
    return f"{key_id}:{token_hash}"


def print_api_key_info(key_id: str, token: str, token_hash: str, env_format: bool = False) -> None:
    """
    Print API key information in a readable format.

    Args:
        key_id: The key ID
        token: The plaintext token
        token_hash: The hashed token
        env_format: Whether to print in environment variable format
    """
    console = Console()

    if env_format:
        rprint("[bold]Environment Variables:[/bold]")
        rprint(f"[yellow]BUTTERCUP_TASK_SERVER_API_KEY_ID[/yellow]={key_id}")
        rprint(f"[yellow]BUTTERCUP_TASK_SERVER_API_TOKEN_HASH[/yellow]={token_hash}")
        rprint("\n[bold]Client Authentication:[/bold]")
        rprint(f"[green]API_KEY_ID[/green]={key_id}")
        rprint(f"[green]API_TOKEN[/green]={token}")
    else:
        table = Table(title="API Key Information")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Key ID", key_id)
        table.add_row("Token", token)
        table.add_row("Token Hash", token_hash)

        console.print(table)

        rprint("\n[bold yellow]Important:[/bold yellow] Store the token securely! It cannot be recovered if lost.")


def main() -> int:
    """
    Main entry point for the CLI tool.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = argparse.ArgumentParser(description="Generate API keys and tokens for the CRS Task Server")
    parser.add_argument("--env", action="store_true", help="Format output as environment variables")
    parser.add_argument(
        "--token-length",
        type=int,
        default=TOKEN_LENGTH,
        help=f"Length of the generated token (default: {TOKEN_LENGTH})",
    )

    args = parser.parse_args()

    try:
        key_id, token, token_hash = generate_api_key()
        print_api_key_info(key_id, token, token_hash, args.env)
        return 0
    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
