"""
Mock Competition API Component.

This module provides a mock implementation of the competition API for testing purposes.
It always returns accepted/passed status for submissions and provides endpoints
to download files from a local tar.gz archive.
"""

import asyncio
import json
import logging
import os
import tarfile
import tempfile
from typing import Dict, List, Optional, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
import shutil
import aiohttp
import base64

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# Models based on the competition API models
class SourceType(str):
    REPO = "repo"
    FUZZ_TOOLING = "fuzz-tooling"
    DIFF = "diff"


class TaskType(str):
    FULL = "full"
    DELTA = "delta"


class SubmissionStatus(str):
    ACCEPTED = "accepted"
    PASSED = "passed"
    FAILED = "failed"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    ERRORED = "errored"


class SourceDetail(BaseModel):
    sha256: str
    type: str
    url: str


class TaskDetail(BaseModel):
    id: str
    type: str
    deadline: str
    source: List[SourceDetail]
    round_id: str
    created_at: str
    updated_at: str
    focus: str
    project_name: str
    commit: str
    harnesses_included: bool


class BundleSubmission(BaseModel):
    broadcast_sarif_id: Optional[str] = None
    description: Optional[str] = None
    freeform_id: Optional[str] = None
    patch_id: Optional[str] = None
    pov_id: Optional[str] = None
    submitted_sarif_id: Optional[str] = None


class BundleSubmissionResponse(BaseModel):
    bundle_id: str
    status: str


class PingResponse(BaseModel):
    status: bool = True
    message: str = "OK"


class CRSConfig(BaseModel):
    """Configuration for CRS task server connection"""

    task_server_url: str = "http://localhost:8000/v1/task/"
    api_key_id: str = ""
    api_token: str = ""
    enabled: bool = False
    base_url: str = "http://localhost:8080"  # Base URL for the mock API itself


# Mock Competition API
class MockCompetitionAPI:
    def __init__(self, tarball_path: Optional[str] = None, crs_config: Optional[CRSConfig] = None):
        self.app = FastAPI(title="Mock Competition API")
        self.tasks: List[TaskDetail] = []
        self.bundles: Dict[str, Dict[str, Any]] = {}

        # Use environment variable for temp dir if provided
        temp_dir_env = os.environ.get("TEMP_DIR")
        if temp_dir_env and os.path.isdir(temp_dir_env):
            logger.info(f"Using configured temp directory: {temp_dir_env}")
            self.temp_dir = temp_dir_env
        else:
            self.temp_dir = tempfile.mkdtemp()
            logger.info(f"Created temporary directory: {self.temp_dir}")

        # Ensure the temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)

        self.tarball_path = tarball_path
        self.file_map: Dict[str, str] = {}
        self.crs_config = crs_config or CRSConfig()

        # Log CRS configuration status at startup
        if self.crs_config.enabled:
            logger.info(f"CRS integration ENABLED - Will send tasks to {self.crs_config.task_server_url}")
            logger.info(
                f"Using API key ID: {self.crs_config.api_key_id[:4]}..."
                if self.crs_config.api_key_id
                else "No API key ID configured"
            )
        else:
            logger.info("CRS integration DISABLED - Will only log tasks")

        self.register_routes()
        self.next_bundle_id = 1000

        # If tarball path is provided at initialization, extract it
        if self.tarball_path and os.path.exists(self.tarball_path):
            self.extract_tarball(self.tarball_path)

    def extract_tarball(self, tarball_path: str):
        """Extract the tarball to a temporary directory and map hash to file paths."""
        if not os.path.exists(tarball_path):
            logger.error(f"Tarball not found: {tarball_path}")
            return False

        try:
            # Clear existing files and mapping
            for file_path in self.file_map.values():
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError as e:
                        logger.debug(f"Failed to remove file {file_path}: {e}")
                        pass
            self.file_map.clear()

            # Create a clean directory for extracted files
            extract_dir = os.path.join(self.temp_dir, "extracted")
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
            os.makedirs(extract_dir, exist_ok=True)

            logger.info(f"Extracting tarball from {tarball_path} to {extract_dir}")
            with tarfile.open(tarball_path, "r:gz") as tar:
                tar.extractall(path=extract_dir)
                # Map the file hashes to their paths
                for member in tar.getmembers():
                    if member.isfile():
                        file_hash = os.path.basename(member.name)
                        file_path = os.path.join(extract_dir, member.name)
                        self.file_map[file_hash] = file_path
                        logger.info(f"Mapped hash {file_hash} to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to extract tarball: {e}")
            return False

    def register_routes(self):
        """Register all the routes for the mock API."""

        # Ping endpoint
        @self.app.get("/v1/ping/", response_model=PingResponse)
        async def ping():
            return PingResponse()

        # POV models
        class POVSubmission(BaseModel):
            architecture: str = "x86_64"
            engine: str = ""
            fuzzer_name: str = ""
            sanitizer: str = ""
            testcase: str = ""  # base64 encoded test case

        class POVSubmissionResponse(BaseModel):
            pov_id: str
            status: str

        # POV submission endpoint
        @self.app.post("/v1/task/{task_id}/pov/", response_model=POVSubmissionResponse)
        async def submit_pov(task_id: str, payload: POVSubmission):
            pov_id = f"pov-{self.next_bundle_id}"
            self.next_bundle_id += 1

            # Save POV data to temp directory
            pov_path = os.path.join(self.temp_dir, f"{pov_id}.pov")
            try:
                # Decode base64 testcase and save it
                testcase_data = base64.b64decode(payload.testcase)
                with open(pov_path, "wb") as buffer:
                    buffer.write(testcase_data)
            except Exception as e:
                logger.error(f"Error decoding base64 testcase: {e}")
                # If base64 decoding fails, just save the raw testcase
                with open(pov_path, "wb") as buffer:
                    buffer.write(payload.testcase.encode())

            self.bundles[pov_id] = {
                "task_id": task_id,
                "file_path": pov_path,
                "engine": payload.engine,
                "fuzzer_name": payload.fuzzer_name,
                "sanitizer": payload.sanitizer,
                "status": SubmissionStatus.ACCEPTED,
                "created_at": datetime.utcnow().isoformat(),
            }

            return POVSubmissionResponse(pov_id=pov_id, status=SubmissionStatus.ACCEPTED)

        # POV status check endpoint
        @self.app.get("/v1/task/{task_id}/pov/{pov_id}/", response_model=POVSubmissionResponse)
        async def get_pov_status(task_id: str, pov_id: str):
            if pov_id not in self.bundles:
                raise HTTPException(status_code=404, detail="POV not found")

            # Always return PASSED status
            _bundle = self.bundles[pov_id].copy()

            return POVSubmissionResponse(pov_id=pov_id, status=SubmissionStatus.PASSED)

        # Patch models
        class PatchSubmission(BaseModel):
            patch: str  # base64 encoded patch

        class PatchSubmissionResponse(BaseModel):
            patch_id: str
            status: str
            functionality_tests_passing: Optional[bool] = None

        # Patch submission endpoint
        @self.app.post("/v1/task/{task_id}/patch/", response_model=PatchSubmissionResponse)
        async def submit_patch(task_id: str, payload: PatchSubmission):
            patch_id = f"patch-{self.next_bundle_id}"
            self.next_bundle_id += 1

            # Save patch file to temp directory
            patch_path = os.path.join(self.temp_dir, f"{patch_id}.patch")
            try:
                # Decode base64 patch and save it
                patch_data = base64.b64decode(payload.patch)
                with open(patch_path, "wb") as buffer:
                    buffer.write(patch_data)
            except Exception as e:
                logger.error(f"Error decoding base64 patch: {e}")
                # If base64 decoding fails, just save the raw patch
                with open(patch_path, "wb") as buffer:
                    buffer.write(payload.patch.encode())

            self.bundles[patch_id] = {
                "task_id": task_id,
                "file_path": patch_path,
                "status": SubmissionStatus.ACCEPTED,
                "created_at": datetime.utcnow().isoformat(),
            }

            return PatchSubmissionResponse(
                patch_id=patch_id, status=SubmissionStatus.ACCEPTED, functionality_tests_passing=None
            )

        # Patch status check endpoint
        @self.app.get("/v1/task/{task_id}/patch/{patch_id}/", response_model=PatchSubmissionResponse)
        async def get_patch_status(task_id: str, patch_id: str):
            if patch_id not in self.bundles:
                raise HTTPException(status_code=404, detail="Patch not found")

            # Always return PASSED status with successful functionality tests
            return PatchSubmissionResponse(
                patch_id=patch_id, status=SubmissionStatus.PASSED, functionality_tests_passing=True
            )

        # Upload tarball endpoint
        @self.app.post("/upload-tarball/")
        async def upload_tarball(file: UploadFile = File(...)):
            try:
                # Ensure temp directory exists
                os.makedirs(self.temp_dir, exist_ok=True)

                # Create a temporary file to store the uploaded tarball
                temp_tarball = os.path.join(self.temp_dir, "uploaded_tarball.tar.gz")
                logger.info(f"Saving uploaded tarball to {temp_tarball}")

                # Write the uploaded file to the temporary location
                with open(temp_tarball, "wb") as buffer:
                    content = await file.read()
                    buffer.write(content)

                # Verify the file was saved correctly
                if not os.path.exists(temp_tarball):
                    logger.error(f"Failed to save tarball to {temp_tarball}")
                    raise HTTPException(status_code=500, detail="Failed to save uploaded file")

                logger.info(f"Tarball saved successfully ({os.path.getsize(temp_tarball)} bytes)")

                # Extract the tarball
                if self.extract_tarball(temp_tarball):
                    return {
                        "message": f"Tarball uploaded and processed successfully. Mapped {len(self.file_map)} files."
                    }
                else:
                    raise HTTPException(status_code=400, detail="Failed to process the uploaded tarball")
            except Exception as e:
                logger.error(f"Error processing uploaded tarball: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

        # Upload and process control file
        @self.app.post("/control-file/")
        async def upload_control_file(file: UploadFile = File(...)):
            try:
                content = await file.read()
                control_data = json.loads(content)
                self.tasks = control_data

                # Schedule the tasks based on relative timing
                self.schedule_tasks()

                return {"message": f"Processed {len(control_data)} tasks"}
            except Exception as e:
                logger.error(f"Error processing control file: {e}")
                raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

        # Bundle submission endpoint
        @self.app.post("/v1/task/{task_id}/bundle/", response_model=BundleSubmissionResponse)
        async def submit_bundle(task_id: str, payload: BundleSubmission):
            bundle_id = f"bundle-{self.next_bundle_id}"
            self.next_bundle_id += 1

            self.bundles[bundle_id] = {
                "task_id": task_id,
                "submission": payload.model_dump(),
                "status": SubmissionStatus.ACCEPTED,
                "created_at": datetime.utcnow().isoformat(),
            }

            return BundleSubmissionResponse(bundle_id=bundle_id, status=SubmissionStatus.ACCEPTED)

        # Get bundle status endpoint
        @self.app.get("/v1/task/{task_id}/bundle/{bundle_id}/")
        async def get_bundle(task_id: str, bundle_id: str):
            if bundle_id not in self.bundles:
                raise HTTPException(status_code=404, detail="Bundle not found")

            # Always return PASSED status with the bundle data
            bundle = self.bundles[bundle_id].copy()

            # For the GET endpoint, we want to include all the submission data plus the status and bundle_id
            response_data = {"bundle_id": bundle_id, "status": SubmissionStatus.PASSED}

            # Add any other fields from the submission
            if "submission" in bundle:
                response_data.update(bundle["submission"])

            return response_data

        # Bundle patch endpoint
        @self.app.patch("/v1/task/{task_id}/bundle/{bundle_id}/", response_model=Dict[str, Any])
        async def patch_bundle(task_id: str, bundle_id: str, payload: BundleSubmission):
            if bundle_id not in self.bundles:
                raise HTTPException(status_code=404, detail="Bundle not found")

            # Update the bundle with the new data
            bundle = self.bundles[bundle_id]
            bundle["submission"].update(payload.model_dump(exclude_unset=True))
            bundle["status"] = SubmissionStatus.ACCEPTED

            return {
                "bundle_id": bundle_id,
                "status": SubmissionStatus.ACCEPTED,
                **payload.model_dump(exclude_unset=True),
            }

        # SARIF assessment models
        class SarifAssessmentSubmission(BaseModel):
            assessment: str = "correct"  # or "incorrect"

        class SarifAssessmentResponse(BaseModel):
            status: str

        # Broadcast SARIF assessment endpoint
        @self.app.post(
            "/v1/task/{task_id}/broadcast-sarif-assessment/{broadcast_sarif_id}/",
            response_model=SarifAssessmentResponse,
        )
        async def submit_broadcast_sarif_assessment(
            task_id: str, broadcast_sarif_id: str, payload: SarifAssessmentSubmission
        ):
            # Store the assessment in bundles for tracking
            sarif_id = f"sarif-assessment-{self.next_bundle_id}"
            self.next_bundle_id += 1

            self.bundles[sarif_id] = {
                "task_id": task_id,
                "broadcast_sarif_id": broadcast_sarif_id,
                "assessment": payload.assessment,
                "status": SubmissionStatus.ACCEPTED,
                "created_at": datetime.utcnow().isoformat(),
            }

            return SarifAssessmentResponse(status=SubmissionStatus.ACCEPTED)

        # File download endpoint
        @self.app.get("/v1/file/{file_hash}")
        async def get_file(file_hash: str):
            if file_hash not in self.file_map:
                raise HTTPException(status_code=404, detail="File not found")

            return FileResponse(self.file_map[file_hash])

        # Get status of file upload
        @self.app.get("/files-status/")
        async def files_status():
            return {
                "tarball_loaded": len(self.file_map) > 0,
                "file_count": len(self.file_map),
                "temp_dir": self.temp_dir,
                "available_hashes": list(self.file_map.keys())[:10] + (["..."] if len(self.file_map) > 10 else []),
            }

    def schedule_tasks(self):
        """Schedule tasks based on created_at timestamps."""
        if not self.tasks:
            return

        # Sort tasks by created_at timestamp
        sorted_tasks = sorted(self.tasks, key=lambda x: x["created_at"])

        # Get the base timestamp from the earliest task
        base_timestamp = datetime.fromisoformat(sorted_tasks[0]["created_at"].replace("Z", "+00:00"))

        async def send_task_with_delay(task, delay):
            # Wait until the specific time when this task should be sent
            if delay > 0:
                logger.info(f"Scheduled task {task['id']} to be sent after {delay} seconds")
                await asyncio.sleep(delay)
            await self.send_task_to_crs(task)

        # Create independent tasks for each send operation
        for task in sorted_tasks:
            current_timestamp = datetime.fromisoformat(task["created_at"].replace("Z", "+00:00"))
            delay = (current_timestamp - base_timestamp).total_seconds()
            # Create an independent task that will execute at the right time
            asyncio.create_task(send_task_with_delay(task, delay))

    async def send_task_to_crs(self, task: Dict[str, Any]):
        """Send a task to the CRS via its task server API."""
        logger.info(f"Sending task to CRS: {task['id']}")

        # Create a copy of the task to avoid modifying the original
        task_copy = task.copy()

        # Update the source URLs to point to our file serving endpoint
        sources = []
        for source in task_copy["source"]:
            source_copy = source.copy()
            file_hash = source_copy["sha256"]
            # Update URL to point to our file endpoint using the configured base URL
            source_copy["url"] = f"{self.crs_config.base_url}/v1/file/{file_hash}"
            sources.append(source_copy)

        # Calculate the adjusted deadline based on current time
        # Get the original time difference between deadline and created_at
        original_created_at = datetime.fromisoformat(task_copy["created_at"].replace("Z", "+00:00"))
        original_deadline = datetime.fromisoformat(task_copy["deadline"].replace("Z", "+00:00"))
        original_time_delta = original_deadline - original_created_at

        # Apply the same time delta to the current time
        current_time = datetime.utcnow()
        adjusted_deadline = current_time + original_time_delta

        logger.info(f"Original created_at: {original_created_at}")
        logger.info(f"Original deadline: {original_deadline}")
        logger.info(f"Time delta: {original_time_delta}")
        logger.info(f"Current time: {current_time}")
        logger.info(f"Adjusted deadline: {adjusted_deadline}")

        # Format the task for CRS with the adjusted deadline
        crs_task = {
            "message_id": f"msg-{task_copy['id']}",
            "message_time": int(current_time.timestamp() * 1000),  # Convert to milliseconds
            "tasks": [
                {
                    "task_id": task_copy["id"],
                    "deadline": int(adjusted_deadline.timestamp() * 1000),  # Convert to milliseconds
                    "focus": task_copy["focus"],
                    "harnesses_included": task_copy["harnesses_included"],
                    "metadata": {},
                    "project_name": task_copy["project_name"],
                    "source": sources,  # Use the updated sources
                    "type": task_copy["type"],
                }
            ],
        }

        # Always log the task for debugging
        logger.info(f"Task for CRS: {json.dumps(crs_task, indent=2)}")

        # Only send to CRS if enabled
        if not self.crs_config.enabled:
            logger.info("CRS integration is disabled. Not sending task to CRS.")
            return

        if not self.crs_config.api_key_id or not self.crs_config.api_token:
            logger.warning("CRS API credentials not configured. Not sending task to CRS.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                # Use HTTP Basic Auth with the configured credentials
                auth = aiohttp.BasicAuth(self.crs_config.api_key_id, self.crs_config.api_token)

                logger.info(f"Sending task to CRS at {self.crs_config.task_server_url}")
                async with session.post(self.crs_config.task_server_url, json=crs_task, auth=auth) as response:
                    if response.status in (200, 201, 202, 204):
                        logger.info(f"Successfully sent task {task_copy['id']} to CRS")
                        try:
                            response_text = await response.text()
                            logger.debug(f"CRS response: {response_text}")
                        except aiohttp.ClientError as e:
                            logger.debug(f"Failed to read response body: {e}")
                            pass
                    else:
                        response_text = await response.text()
                        logger.error(f"Failed to send task to CRS: HTTP {response.status}, Response: {response_text}")
        except Exception as e:
            logger.error(f"Error sending task to CRS: {str(e)}")

    def run(self, host: str = "0.0.0.0", port: int = 8080):
        """Run the mock API server."""
        uvicorn.run(self.app, host=host, port=port)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Mock Competition API Server")
    parser.add_argument("--tarball", required=False, help="Path to the tarball containing files to serve")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind the server to")
    parser.add_argument("--crs-url", default="http://localhost:8000/v1/task/", help="CRS task server URL")
    parser.add_argument("--crs-key-id", default="", help="CRS API key ID for authentication")
    parser.add_argument("--crs-token", default="", help="CRS API token for authentication")
    parser.add_argument("--crs-enabled", action="store_true", help="Enable sending tasks to CRS")
    parser.add_argument(
        "--base-url", default="http://localhost:8080", help="Base URL for the mock API (used in file URLs sent to CRS)"
    )

    args = parser.parse_args()

    # Create CRS config from args
    crs_config = CRSConfig(
        task_server_url=args.crs_url,
        api_key_id=args.crs_key_id,
        api_token=args.crs_token,
        enabled=args.crs_enabled,
        base_url=args.base_url,
    )

    api = MockCompetitionAPI(args.tarball, crs_config)
    api.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
