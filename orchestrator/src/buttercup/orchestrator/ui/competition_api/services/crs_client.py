from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from buttercup.orchestrator.ui.competition_api.models.crs_types import SARIFBroadcast, Task

logger = logging.getLogger(__name__)


class CRSResponse:
    """Response from CRS API calls with detailed status and error information."""

    def __init__(
        self, success: bool, status_code: int, response_text: str = "", error_details: Optional[Dict[str, Any]] = None
    ):
        self.success = success
        self.status_code = status_code
        self.response_text = response_text
        self.error_details = error_details or {}

    def get_user_friendly_error_message(self, base_message: str = "Operation failed") -> str:
        """
        Generate a user-friendly error message from the response details.

        Args:
            base_message: Base message to start with

        Returns:
            Formatted error message suitable for display to users
        """
        if self.success:
            return ""

        error_message = base_message

        # Add specific error information
        if self.error_details.get("error_message"):
            error_message += f": {self.error_details['error_message']}"

        # Add validation errors if present
        validation_errors = self.error_details.get("validation_errors", {})
        if validation_errors:
            if isinstance(validation_errors, dict):
                # Format validation errors in a user-friendly way
                formatted_errors = []
                for field, error in validation_errors.items():
                    if isinstance(error, list):
                        formatted_errors.append(f"{field}: {', '.join(error)}")
                    else:
                        formatted_errors.append(f"{field}: {error}")
                error_message += f". Validation errors: {'; '.join(formatted_errors)}"
            else:
                error_message += f". Validation errors: {validation_errors}"

        # Add error code if present
        if self.error_details.get("error_code"):
            error_message += f" (Error code: {self.error_details['error_code']})"

        # Add HTTP status code information if it's not a standard success code
        if self.status_code not in (200, 202):
            error_message += f" (HTTP status: {self.status_code})"

        return error_message

    def log_detailed_response(self, logger_instance: logging.Logger, operation: str = "CRS operation") -> None:
        """
        Log detailed response information for debugging purposes.

        Args:
            logger_instance: Logger instance to use
            operation: Description of the operation being logged
        """
        if self.success:
            logger_instance.info(f"{operation} completed successfully (HTTP {self.status_code})")
        else:
            logger_instance.error(f"{operation} failed (HTTP {self.status_code})")
            logger_instance.error(f"Response text: {self.response_text}")

            if self.error_details:
                logger_instance.error(f"Error details: {self.error_details}")

                # Log specific error information
                if self.error_details.get("error_message"):
                    logger_instance.error(f"Error message: {self.error_details['error_message']}")

                if self.error_details.get("error_code"):
                    logger_instance.error(f"Error code: {self.error_details['error_code']}")

                if self.error_details.get("validation_errors"):
                    logger_instance.error(f"Validation errors: {self.error_details['validation_errors']}")

                if self.error_details.get("status"):
                    logger_instance.error(f"Status: {self.error_details['status']}")

                if self.error_details.get("success_indicator") is not None:
                    logger_instance.error(f"Success indicator: {self.error_details['success_indicator']}")

                if self.error_details.get("accepted") is not None:
                    logger_instance.error(f"Accepted: {self.error_details['accepted']}")

                if self.error_details.get("valid") is not None:
                    logger_instance.error(f"Valid: {self.error_details['valid']}")

    @classmethod
    def from_response(cls, response: requests.Response) -> CRSResponse:
        """Create a CRSResponse from a requests.Response object."""
        try:
            # Try to parse JSON response for detailed error information
            response_data = response.json()

            # Check if the response indicates success despite HTTP status
            # Look for common error indicators in the response body
            if isinstance(response_data, dict):
                # Check for various error fields that might be present in the response
                error_message = (
                    response_data.get("error", "")
                    or response_data.get("message", "")
                    or response_data.get("detail", "")
                    or response_data.get("reason", "")
                )
                error_code = response_data.get("error_code", "") or response_data.get("code", "")
                validation_errors = (
                    response_data.get("validation_errors", {})
                    or response_data.get("errors", {})
                    or response_data.get("field_errors", {})
                    or response_data.get("constraint_violations", {})
                )

                # Check for success/failure indicators in the response
                status = response_data.get("status", "").lower()
                success_indicator = response_data.get("success", None)

                # Look for additional failure indicators
                has_failure_indicators = (
                    error_message
                    or error_code
                    or validation_errors
                    or status in ["error", "failed", "failure", "invalid", "rejected"]
                    or success_indicator is False
                    or response_data.get("accepted", True) is False
                    or response_data.get("valid", True) is False
                )

                # Determine if this is actually a success or failure
                # Even with 200/202 status, the response body might indicate failure
                is_success = response.status_code in (200, 202) and not has_failure_indicators

                return cls(
                    success=is_success,
                    status_code=response.status_code,
                    response_text=response.text,
                    error_details={
                        "error_message": error_message,
                        "error_code": error_code,
                        "validation_errors": validation_errors,
                        "status": status,
                        "success_indicator": success_indicator,
                        "accepted": response_data.get("accepted"),
                        "valid": response_data.get("valid"),
                        "raw_response": response_data,
                    },
                )
            # Non-JSON response, treat as success if status is 200/202
            return cls(
                success=response.status_code in (200, 202),
                status_code=response.status_code,
                response_text=response.text,
            )

        except (ValueError, TypeError):
            # Response is not valid JSON, treat as success if status is 200/202
            return cls(
                success=response.status_code in (200, 202),
                status_code=response.status_code,
                response_text=response.text,
            )


class CRSClient:
    def __init__(self, crs_base_url: str, username: str | None = None, password: str | None = None) -> None:
        self.crs_base_url = crs_base_url.rstrip("/")
        self.username = username
        self.password = password

    def submit_task(self, task: Task) -> CRSResponse:
        """
        Submit a task to the CRS via POST /v1/task endpoint

        Args:
            task: Task object to submit

        Returns:
            CRSResponse object with detailed status and error information

        """
        url = f"{self.crs_base_url}/v1/task/"

        # Prepare authentication if provided
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            logger.info(f"Submitting task {task.tasks[0].task_id} to CRS at {url}")

            response = requests.post(
                url,
                json=task.model_dump(),
                auth=auth,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            # Create detailed response object
            crs_response = CRSResponse.from_response(response)

            # Log detailed response information
            crs_response.log_detailed_response(logger, f"Task submission for {task.tasks[0].task_id}")

            return crs_response

        except Exception as e:
            logger.error(f"Error submitting task to CRS: {e}")
            return CRSResponse(success=False, status_code=0, response_text=str(e), error_details={"exception": str(e)})

    def submit_sarif_broadcast(self, broadcast: SARIFBroadcast) -> CRSResponse:
        """
        Submit a SARIF Broadcast to the CRS via POST /v1/sarif/ endpoint
        """
        url = f"{self.crs_base_url}/v1/sarif/"

        # Prepare authentication if provided
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            logger.info(f"Submitting SARIF Broadcasts for {len(broadcast.broadcasts)} tasks to CRS at {url}")

            response = requests.post(
                url,
                json=broadcast.model_dump(),
                auth=auth,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            # Create detailed response object
            crs_response = CRSResponse.from_response(response)

            # Log detailed response information
            crs_response.log_detailed_response(
                logger, f"SARIF Broadcast submission for {len(broadcast.broadcasts)} tasks"
            )

            return crs_response

        except Exception as e:
            logger.error(f"Error submitting SARIF Broadcasts to CRS: {e}")
            return CRSResponse(success=False, status_code=0, response_text=str(e), error_details={"exception": str(e)})

    def ping(self) -> bool:
        """Test connectivity to CRS via GET /status/ endpoint

        Returns:
            True if CRS is reachable and ready, False otherwise

        """
        url = f"{self.crs_base_url}/status/"

        # Prepare authentication if provided
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            logger.info(f"Pinging CRS at {url}")

            response = requests.get(
                url,
                auth=auth,
                timeout=10,
            )

            if response.status_code == 200:
                status_data = response.json()
                ready = status_data.get("ready", False)
                logger.info(f"CRS ping successful. Ready: {ready}")
                return bool(ready)
            logger.error(f"CRS ping failed. Status: {response.status_code}, Response: {response.text}")
            return False

        except Exception as e:
            logger.error(f"Error pinging CRS: {e}")
            return False
