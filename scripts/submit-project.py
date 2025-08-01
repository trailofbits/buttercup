#!/usr/bin/env python3
"""
Interactive script to submit custom challenges to Buttercup CRS.

This script guides users through submitting challenges by asking questions
to determine the proper parameters for the /webhook/trigger_task endpoint.
"""

import argparse
import json
import requests
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def run_git_command(cmd: list[str], cwd: Optional[Path] = None) -> str:
    """Run a git command and return its output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running git command: {e}")
        print(f"Error output: {e.stderr}")
        sys.exit(1)


def get_default_branch(repo_url: str) -> str:
    """Get the default branch of a git repository."""
    try:
        # Use git ls-remote to get the default branch
        result = subprocess.run(
            ["git", "ls-remote", "--symref", repo_url, "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        
        for line in result.stdout.split('\n'):
            if line.startswith('ref: refs/heads/'):
                # Format is "ref: refs/heads/branch<TAB>HEAD"
                parts = line.split('/')
                if len(parts) >= 3:
                    branch_part = parts[-1]
                    tab_parts = branch_part.split('\t')
                    if tab_parts:
                        return tab_parts[0].strip()
        
        # Fallback to common default branch names
        return "main"
    except subprocess.CalledProcessError:
        print(f"Warning: Could not determine default branch for {repo_url}, using 'main'")
        return "main"


def validate_git_repo(repo_url: str) -> bool:
    """Validate that a git repository URL is accessible."""
    try:
        subprocess.run(
            ["git", "ls-remote", repo_url, "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def ask_yes_no(question: str, default: bool = True) -> bool:
    """Ask a yes/no question with a default value."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{question} [{default_str}]: ").strip().lower()
        if not response:
            return default
        if response in ('y', 'yes'):
            return True
        if response in ('n', 'no'):
            return False
        print("Please answer 'y' or 'n'")


def ask_string(question: str, default: Optional[str] = None, required: bool = True) -> str:
    """Ask for a string input with optional default."""
    prompt = f"{question}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    
    while True:
        response = input(prompt).strip()
        if response:
            return response
        if default:
            return default
        if not required:
            return ""
        print("This field is required.")


def ask_integer(question: str, default: Optional[int] = None, min_val: int = 1) -> int:
    """Ask for an integer input with optional default and validation."""
    prompt = f"{question}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    
    while True:
        response = input(prompt).strip()
        if not response and default is not None:
            return default
        
        try:
            value = int(response)
            if value < min_val:
                print(f"Value must be at least {min_val}")
                continue
            return value
        except ValueError:
            print("Please enter a valid integer")


def get_challenge_repo_from_ossfuzz_project(project_name: str) -> Optional[str]:
    """Attempt to determine challenge repository URL from OSS-Fuzz project name."""
    if not HAS_YAML:
        return None
        
    project_yaml_url = f"https://raw.githubusercontent.com/google/oss-fuzz/master/projects/{project_name}/project.yaml"
    
    try:
        response = requests.get(project_yaml_url, timeout=10)
        if response.status_code == 200:
            project_config = yaml.safe_load(response.text)
            if isinstance(project_config, dict) and 'main_repo' in project_config:
                return project_config['main_repo']
    except Exception:
        # If we can't determine it automatically, that's fine - user can specify manually
        pass
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Submit custom challenges to Buttercup CRS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python submit-project.py
  python submit-project.py --api-url http://localhost:31323
  python submit-project.py --dry-run
        """
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:31323",
        help="Base URL for the competition API (default: http://127.0.0.1:31323)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the request that would be made without actually sending it"
    )
    
    args = parser.parse_args()
    
    print("=== Buttercup CRS Challenge Submission ===")
    print()
    
    # Fuzzing tooling questions (ask first)
    print("Fuzzing Configuration:")
    use_upstream_oss_fuzz = ask_yes_no("Do you want to use upstream google/oss-fuzz?", True)
    
    if use_upstream_oss_fuzz:
        fuzz_tooling_url = "https://github.com/google/oss-fuzz"
        fuzz_tooling_ref = "master"
        
        # Get project name and try to auto-detect challenge repo
        fuzz_tooling_project_name = ask_string("OSS-Fuzz project name")
        
        print("Attempting to auto-detect challenge repository from OSS-Fuzz project...")
        auto_detected_repo = get_challenge_repo_from_ossfuzz_project(fuzz_tooling_project_name)
        
        if auto_detected_repo:
            print(f"Auto-detected challenge repository: {auto_detected_repo}")
            use_auto_detected = ask_yes_no("Use this repository?", True)
            if use_auto_detected:
                challenge_repo_url = auto_detected_repo
            else:
                challenge_repo_url = ask_string("Challenge repository URL")
        else:
            if not HAS_YAML:
                print("Note: Install PyYAML for automatic repository detection from OSS-Fuzz projects")
            else:
                print("Could not auto-detect repository from OSS-Fuzz project")
            challenge_repo_url = ask_string("Challenge repository URL")
    else:
        fuzz_tooling_url = ask_string("Custom oss-fuzz repository URL")
        fuzz_tooling_ref = ask_string("OSS-Fuzz repository reference", "master")
        fuzz_tooling_project_name = ask_string("OSS-Fuzz project name")
        challenge_repo_url = ask_string("Challenge repository URL")
    
    # Validate the repository URL
    print()
    print("Validating repository URL...")
    if not validate_git_repo(challenge_repo_url):
        print(f"Error: Could not access repository at {challenge_repo_url}")
        print("Please check the URL and your network connection.")
        sys.exit(1)
    print("✓ Repository URL is valid")
    
    # Branch/commit analysis
    print()
    print("Challenge Repository Analysis:")
    analyze_specific_ref = ask_yes_no("Do you want to analyze a specific branch/commit?", False)
    
    if analyze_specific_ref:
        head_ref = ask_string("Enter branch name or commit hash")
        
        # Check if it's a diff mode (contains "..")
        if ".." in head_ref:
            print("Detected diff mode (range with '..')")
            challenge_repo_head_ref = head_ref.split("..")[-1]
            challenge_repo_base_ref = head_ref.split("..")[0]
        else:
            challenge_repo_head_ref = head_ref
            use_base_ref = ask_yes_no("Do you want to specify a base reference for comparison?", False)
            if use_base_ref:
                challenge_repo_base_ref = ask_string("Base reference (branch/commit)")
            else:
                challenge_repo_base_ref = None
    else:
        # Use default branch
        print("Getting default branch...")
        default_branch = get_default_branch(challenge_repo_url)
        print(f"Using default branch: {default_branch}")
        challenge_repo_head_ref = default_branch
        challenge_repo_base_ref = None
    
    # Harnesses are always included (non-configurable as per review)
    harnesses_included = True
    
    # Duration
    print()
    duration_minutes = ask_integer("Analysis duration in minutes", 30, 1)
    duration_seconds = duration_minutes * 60
    
    # Build the request payload
    payload = {
        "challenge_repo_url": challenge_repo_url,
        "challenge_repo_head_ref": challenge_repo_head_ref,
        "fuzz_tooling_url": fuzz_tooling_url,
        "fuzz_tooling_ref": fuzz_tooling_ref,
        "fuzz_tooling_project_name": fuzz_tooling_project_name,
        "harnesses_included": harnesses_included,
        "duration": duration_seconds
    }
    
    if challenge_repo_base_ref:
        payload["challenge_repo_base_ref"] = challenge_repo_base_ref
    
    # Show summary
    print()
    print("=== Submission Summary ===")
    print(f"Challenge Repository: {challenge_repo_url}")
    print(f"Head Reference: {challenge_repo_head_ref}")
    if challenge_repo_base_ref:
        print(f"Base Reference: {challenge_repo_base_ref}")
    print(f"Fuzz Tooling: {fuzz_tooling_url} @ {fuzz_tooling_ref}")
    print(f"Project Name: {fuzz_tooling_project_name}")
    print(f"Harnesses Included: {harnesses_included}")
    print(f"Duration: {duration_minutes} minutes ({duration_seconds} seconds)")
    print()
    
    if args.dry_run:
        print("=== Dry Run - Request Payload ===")
        print(json.dumps(payload, indent=2))
        print()
        print(f"Would POST to: {args.api_url}/webhook/trigger_task")
        return
    
    # Confirm submission
    if not ask_yes_no("Proceed with submission?", True):
        print("Submission cancelled.")
        return
    
    # Make the API request
    api_url = f"{args.api_url}/webhook/trigger_task"
    print(f"Submitting to {api_url}...")
    
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✓ Submission successful!")
            if "message" in result:
                print(f"Message: {result['message']}")
        else:
            print(f"✗ Submission failed with status {response.status_code}")
            try:
                error_data = response.json()
                if "message" in error_data:
                    print(f"Error: {error_data['message']}")
                else:
                    print(f"Error response: {error_data}")
            except json.JSONDecodeError:
                print(f"Error response: {response.text}")
    
    except requests.RequestException as e:
        print(f"✗ Network error: {e}")
        print("Make sure the CRS is running and accessible at the specified URL.")
        print("You can check with: kubectl port-forward -n crs service/buttercup-competition-api 31323:1323")


if __name__ == "__main__":
    main()