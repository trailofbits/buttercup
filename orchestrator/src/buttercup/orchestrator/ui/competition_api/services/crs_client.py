from __future__ import annotations

import logging
import requests
from typing import Optional

from buttercup.orchestrator.ui.competition_api.models.crs_types import Task

logger = logging.getLogger(__name__)


class CRSClient:
    def __init__(self, crs_base_url: str, username: Optional[str] = None, password: Optional[str] = None) -> None:
        self.crs_base_url = crs_base_url.rstrip("/")
        self.username = username
        self.password = password

    def submit_task(self, task: Task) -> bool:
        """
        Submit a task to the CRS via POST /v1/task endpoint

        Args:
            task: Task object to submit

        Returns:
            True if successful, False otherwise
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

            if response.status_code in (202, 200):
                logger.info(f"Task {task.tasks[0].task_id} submitted successfully to CRS")
                return True
            else:
                logger.error(f"Failed to submit task to CRS. Status: {response.status_code}, Response: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error submitting task to CRS: {e}")
            return False

    def ping(self) -> bool:
        """
        Test connectivity to CRS via GET /status/ endpoint

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
            else:
                logger.error(f"CRS ping failed. Status: {response.status_code}, Response: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error pinging CRS: {e}")
            return False
