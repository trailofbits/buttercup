#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests>=2.31.0",
# ]
# ///
"""
Submit local challenges to Buttercup CRS for analysis.

This script packages local OSS-Fuzz projects and submits them to the CRS
for vulnerability discovery and fuzzing.
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth


# Configuration from .env
CRS_API_URL = "http://localhost:8000"
CRS_API_KEY_ID = "515cc8a0-3019-4c9f-8c1c-72d0b54ae561"
CRS_API_TOKEN = "VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB"
FILE_SERVER_PORT = 8888


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class SourceDetail:
    """Source tarball details."""
    sha256: str
    type: str  # "repo", "fuzz-tooling", or "diff"
    url: str


@dataclass
class TaskDetail:
    """Task submission details."""
    task_id: str
    type: str  # "full" or "delta"
    deadline: int
    source: List[SourceDetail]
    focus: str
    project_name: str
    harnesses_included: bool
    metadata: Dict[str, str]


@dataclass
class Task:
    """Task message for submission."""
    message_id: str
    message_time: int
    tasks: List[TaskDetail]


class FileServer:
    """Simple HTTP file server for serving tarballs."""
    
    def __init__(self, directory: Path, port: int = FILE_SERVER_PORT):
        self.directory = directory
        self.port = port
        self.server = None
        self.thread = None
        self.download_count = 0
        self.expected_files = []
        
    def start(self):
        """Start the file server in a background thread."""
        os.chdir(self.directory)
        
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                """Handle GET requests with logging."""
                file_path = self.path.lstrip('/')
                client_addr = self.client_address[0]
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Get file size if exists
                try:
                    file_size = os.path.getsize(file_path)
                    size_str = f" ({file_size:,} bytes)"
                except:
                    size_str = ""
                
                # Log the request
                logger.info(f"[{timestamp}] 📥 Download request: {file_path}{size_str} from {client_addr}")
                
                # Store original path for logging
                requested_file = file_path
                
                # Call parent to actually serve the file
                super().do_GET()
                
                # Check response status from headers
                response_code = getattr(self, '_status_code', 200)
                
                # Log completion based on response
                if response_code == 200:
                    self.server.download_count += 1
                    logger.info(f"[{timestamp}] ✅ Download complete: {requested_file} ({self.server.download_count}/{len(self.server.expected_files)} files)")
                elif response_code == 404:
                    logger.warning(f"[{timestamp}] ❌ File not found: {requested_file}")
                else:
                    logger.warning(f"[{timestamp}] ⚠️  Download failed: {requested_file} (HTTP {response_code})")
                    
            def send_response(self, code, message=None):
                """Override to capture response code."""
                self._status_code = code
                super().send_response(code, message)
            
            def log_message(self, format, *args):
                # Suppress default console logging
                pass
                
        self.server = HTTPServer(("0.0.0.0", self.port), Handler)
        # Add attributes to the server instance
        self.server.download_count = self.download_count
        self.server.expected_files = self.expected_files
        
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"File server started on port {self.port}")
        
    def stop(self):
        """Stop the file server."""
        if self.server:
            self.server.shutdown()
            self.thread.join()
            logger.info("File server stopped")
            
    def get_url(self, filename: str) -> str:
        """Get URL for a file."""
        # Use host.docker.internal for Docker containers to reach host
        # This works on Docker Desktop for Mac/Windows
        return f"http://host.docker.internal:{self.port}/{filename}"


def create_tarball(source_dir: Path, output_file: Path, base_name: Optional[str] = None) -> str:
    """Create a tarball from a directory and return its SHA256 hash."""
    logger.info(f"Creating tarball from {source_dir} to {output_file}")
    
    with tarfile.open(output_file, "w:gz") as tar:
        if base_name:
            # Add files under a specific base directory name
            for item in source_dir.iterdir():
                arcname = os.path.join(base_name, item.name)
                tar.add(item, arcname=arcname)
        else:
            # Add files directly
            tar.add(source_dir, arcname=".")
    
    # Calculate SHA256
    with open(output_file, "rb") as f:
        sha256_hash = hashlib.sha256(f.read()).hexdigest()
    
    logger.info(f"Created tarball: {output_file.name} (SHA256: {sha256_hash})")
    return sha256_hash


def extract_git_diff(repo_path: Path, commit1: str, commit2: str, output_dir: Path) -> Optional[Path]:
    """Extract git diff between two commits."""
    logger.info(f"Extracting diff between {commit1} and {commit2}")
    
    try:
        # Get the diff
        result = subprocess.run(
            ["git", "diff", f"{commit1}..{commit2}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        if not result.stdout:
            logger.warning("No differences found between commits")
            return None
            
        # Save diff to file
        diff_file = output_dir / "changes.diff"
        diff_file.write_text(result.stdout)
        
        logger.info(f"Saved diff to {diff_file}")
        return diff_file
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to extract git diff: {e}")
        return None


def find_project_name(source_dir: Path) -> str:
    """Extract project name from OSS-Fuzz structure."""
    # Look for projects directory
    projects_dir = source_dir / "projects"
    if projects_dir.exists() and projects_dir.is_dir():
        # Get first project directory (excluding infra)
        for item in projects_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.') and item.name != 'infra':
                # Verify it's a real project by checking for project.yaml
                if (item / "project.yaml").exists():
                    return item.name
                
    # Fallback to directory name
    return source_dir.name


def find_focus_directory(source_dir: Path) -> str:
    """Find the focus directory (main project source) within the structure."""
    # Common patterns for source locations
    candidates = [
        "src",
        "source",
        ".",  # Root directory
    ]
    
    for candidate in candidates:
        if (source_dir / candidate).exists():
            return candidate
            
    # Default to root
    return "."


def validate_oss_fuzz_structure(source_dir: Path) -> bool:
    """Validate that directory has OSS-Fuzz structure."""
    required_paths = [
        "projects",  # OSS-Fuzz projects directory
    ]
    
    for path in required_paths:
        if not (source_dir / path).exists():
            logger.error(f"Missing required OSS-Fuzz path: {path}")
            return False
            
    return True


def prepare_challenge(
    source_dir: Path,
    work_dir: Path,
    commit1: Optional[str] = None,
    commit2: Optional[str] = None
) -> Tuple[List[Path], str, str, bool]:
    """
    Prepare challenge tarballs.
    
    Returns: (tarball_paths, project_name, focus, is_delta)
    """
    tarballs = []
    is_delta = commit1 and commit2
    
    # Validate OSS-Fuzz structure
    if not validate_oss_fuzz_structure(source_dir):
        raise ValueError("Invalid OSS-Fuzz project structure")
    
    # Extract project info
    project_name = find_project_name(source_dir)
    focus = find_focus_directory(source_dir)
    
    logger.info(f"Project: {project_name}, Focus: {focus}")
    
    # Create source tarball (excluding OSS-Fuzz tooling)
    source_tarball = work_dir / "source.tar.gz"
    source_content = work_dir / "source_content"
    source_content.mkdir()
    
    # Copy source files (excluding projects directory)
    for item in source_dir.iterdir():
        if item.name != "projects" and not item.name.startswith('.'):
            if item.is_dir():
                shutil.copytree(item, source_content / item.name)
            else:
                shutil.copy2(item, source_content)
                
    sha256 = create_tarball(source_content, source_tarball)
    tarballs.append((source_tarball, sha256, "repo"))
    
    # Create fuzz-tooling tarball (OSS-Fuzz structure with infra and projects dirs)
    if (source_dir / "projects").exists():
        fuzz_tarball = work_dir / "fuzz-tooling.tar.gz"
        
        # Create a temporary directory with the correct OSS-Fuzz structure
        fuzz_content = work_dir / "fuzz_content"
        fuzz_content.mkdir()
        
        # Copy the projects directory
        shutil.copytree(source_dir / "projects", fuzz_content / "projects")
        
        # Copy the infra directory if it exists
        if (source_dir / "infra").exists():
            shutil.copytree(source_dir / "infra", fuzz_content / "infra")
        
        # Create the tarball from this directory
        sha256 = create_tarball(fuzz_content, fuzz_tarball)
        tarballs.append((fuzz_tarball, sha256, "fuzz-tooling"))
    
    # Create diff tarball if delta mode
    if is_delta:
        diff_dir = work_dir / "diff_content"
        diff_dir.mkdir()
        
        diff_file = extract_git_diff(source_dir, commit1, commit2, diff_dir)
        if diff_file:
            diff_tarball = work_dir / "diff.tar.gz"
            sha256 = create_tarball(diff_dir, diff_tarball)
            tarballs.append((diff_tarball, sha256, "diff"))
        else:
            raise ValueError("Failed to extract git diff")
    
    return tarballs, project_name, focus, is_delta


def submit_task(
    tarballs: List[Tuple[Path, str, str]],
    project_name: str,
    focus: str,
    is_delta: bool,
    file_server: FileServer,
    deadline_hours: int = 24
) -> str:
    """Submit task to CRS API."""
    # Create task ID
    task_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    
    # Set expected files for download tracking
    file_server.expected_files = [tarball_path.name for tarball_path, _, _ in tarballs]
    
    # Create source details
    sources = []
    for tarball_path, sha256, source_type in tarballs:
        sources.append(SourceDetail(
            sha256=sha256,
            type=source_type,
            url=file_server.get_url(tarball_path.name)
        ))
    
    # Create task detail
    current_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    deadline = current_time + (deadline_hours * 3600 * 1000)
    
    task_detail = TaskDetail(
        task_id=task_id,
        type="delta" if is_delta else "full",
        deadline=deadline,
        source=sources,
        focus=focus,
        project_name=project_name,
        harnesses_included=True,  # Harnesses are included in the OSS-Fuzz project
        metadata={
            "submitted_via": "local-script",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )
    
    # Create task message
    task = Task(
        message_id=message_id,
        message_time=current_time,
        tasks=[task_detail]
    )
    
    # Submit to API
    url = urljoin(CRS_API_URL, "/v1/task/")
    auth = HTTPBasicAuth(CRS_API_KEY_ID, CRS_API_TOKEN)
    
    # Convert dataclasses to dict for JSON serialization
    task_dict = asdict(task)
    
    logger.info(f"Submitting task {task_id} to {url}")
    logger.info(f"Project: {project_name}, Type: {'Delta' if is_delta else 'Full'} analysis")
    logger.debug(f"Task data: {json.dumps(task_dict, indent=2)}")
    
    try:
        response = requests.post(
            url,
            json=task_dict,
            auth=auth,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        logger.info(f"Task submitted successfully: {task_id}")
        return task_id
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to submit task: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response: {e.response.text}")
        raise


def monitor_task(task_id: str, timeout: int = 300):
    """Monitor task progress (basic implementation)."""
    logger.info(f"Monitoring task {task_id}")
    
    # Note: The CRS doesn't expose a direct task status endpoint
    # In production, you would monitor via:
    # 1. Redis queue status
    # 2. Log aggregation
    # 3. Custom status endpoint
    
    logger.info("Task submitted. Check logs for progress:")
    logger.info("  - docker compose logs scheduler -f")
    logger.info("  - docker compose logs unified-fuzzer -f")
    logger.info("  - docker compose logs patcher -f")


def main():
    parser = argparse.ArgumentParser(
        description="Submit local challenges to Buttercup CRS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full analysis
  %(prog)s /path/to/oss-fuzz-project
  
  # Delta analysis with git commits
  %(prog)s /path/to/oss-fuzz-project --commit1 abc123 --commit2 def456
        """
    )
    
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Path to OSS-Fuzz project directory"
    )
    
    parser.add_argument(
        "--commit1",
        help="First git commit for delta analysis"
    )
    
    parser.add_argument(
        "--commit2", 
        help="Second git commit for delta analysis"
    )
    
    parser.add_argument(
        "--deadline",
        type=int,
        default=24,
        help="Task deadline in hours (default: 24)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=FILE_SERVER_PORT,
        help=f"Port for file server (default: {FILE_SERVER_PORT})"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate arguments
    if not args.source_dir.exists():
        logger.error(f"Source directory not found: {args.source_dir}")
        sys.exit(1)
        
    if (args.commit1 and not args.commit2) or (args.commit2 and not args.commit1):
        logger.error("Both --commit1 and --commit2 must be specified for delta analysis")
        sys.exit(1)
    
    # Create work directory
    with tempfile.TemporaryDirectory() as work_dir:
        work_path = Path(work_dir)
        
        try:
            # Prepare challenge
            logger.info(f"Preparing challenge from {args.source_dir}")
            tarballs, project_name, focus, is_delta = prepare_challenge(
                args.source_dir,
                work_path,
                args.commit1,
                args.commit2
            )
            
            # Start file server
            file_server = FileServer(work_path, args.port)
            file_server.start()
            
            # Give server time to start
            time.sleep(1)
            
            try:
                # Submit task
                task_id = submit_task(
                    tarballs,
                    project_name,
                    focus,
                    is_delta,
                    file_server,
                    args.deadline
                )
                
                # Monitor progress
                monitor_task(task_id)
                
                # Keep server running to allow downloads
                logger.info(f"\n📡 File server running at http://localhost:{file_server.port}")
                logger.info(f"Expecting {len(file_server.expected_files)} files to be downloaded by CRS")
                logger.info("Watch for download requests above...")
                
                # Wait for downloads with periodic status
                start_time = time.time()
                last_count = 0
                while time.time() - start_time < 60:
                    time.sleep(5)
                    elapsed = int(time.time() - start_time)
                    
                    # Check if all files downloaded
                    if file_server.server and file_server.server.download_count >= len(file_server.expected_files):
                        logger.info(f"\n✅ All files downloaded! Waiting 5 more seconds...")
                        time.sleep(5)
                        break
                    
                    # Show status if no new downloads
                    current_count = file_server.server.download_count if file_server.server else 0
                    if current_count == last_count:
                        logger.info(f"⏳ Waiting for downloads... ({elapsed}s elapsed, auto-stop at 60s)")
                    last_count = current_count
                
            finally:
                file_server.stop()
                
        except Exception as e:
            logger.error(f"Failed to submit challenge: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()