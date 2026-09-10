from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, computed_field
from redis import Redis

logger = logging.getLogger(__name__)


class SARIFBroadcastDetail(BaseModel):
    """Model for SARIF broadcast details, matches the model in types.py"""

    metadata: dict[str, Any] = Field(
        ...,
        description="String to string map containing data that should be attached to outputs "
        "like log messages and OpenTelemetry trace attributes for traceability",
    )
    sarif: dict[str, Any] = Field(..., description="SARIF Report compliant with provided schema")
    sarif_id: str
    task_id: str


class Finding(BaseModel):
    """Individual vulnerability finding extracted from a SARIF result."""

    rule_id: str
    level: str
    message: str
    file_uri: str
    start_line: int
    end_line: int
    start_column: int | None = None
    tool_name: str
    sarif_id: str
    task_id: str

    @computed_field
    @property
    def fingerprint(self) -> str:
        return f"{self.rule_id}:{self.file_uri}:{self.start_line}:{self.end_line}"


def _extract_finding_from_result(
    result: dict[str, Any],
    tool_name: str,
    sarif_id: str,
    task_id: str,
) -> Finding | None:
    """Extract a Finding from a single SARIF result entry.

    Returns None if the result is malformed or missing required fields.
    """
    rule_id = result.get("ruleId", "")
    if not rule_id:
        rule = result.get("rule", {})
        rule_id = rule.get("id", "unknown")

    level = result.get("level", "warning")
    message_obj = result.get("message", {})
    message = message_obj.get("text", "") if isinstance(message_obj, dict) else str(message_obj)

    locations = result.get("locations", [])
    if not locations:
        return None

    physical = locations[0].get("physicalLocation", {})
    artifact_location = physical.get("artifactLocation", {})
    file_uri = artifact_location.get("uri", "")
    if not file_uri:
        return None

    region = physical.get("region", {})
    start_line = region.get("startLine", 0)
    if start_line == 0:
        return None

    end_line = region.get("endLine", start_line)
    start_column = region.get("startColumn")

    return Finding(
        rule_id=rule_id,
        level=level,
        message=message,
        file_uri=file_uri,
        start_line=start_line,
        end_line=end_line,
        start_column=start_column,
        tool_name=tool_name,
        sarif_id=sarif_id,
        task_id=task_id,
    )


def extract_findings(sarif_detail: SARIFBroadcastDetail) -> list[Finding]:
    """Extract individual findings from a SARIF broadcast detail.

    Iterates over runs[].results[] and extracts actionable fields.
    Skips malformed entries gracefully.
    """
    findings: list[Finding] = []
    sarif = sarif_detail.sarif
    runs = sarif.get("runs", [])

    for run in runs:
        driver = run.get("tool", {}).get("driver", {})
        tool_name = driver.get("name", "unknown")
        results = run.get("results", [])

        for result in results:
            finding = _extract_finding_from_result(
                result,
                tool_name,
                sarif_detail.sarif_id,
                sarif_detail.task_id,
            )
            if finding is not None:
                findings.append(finding)

    return findings


class SARIFStore:
    """Store and retrieve SARIF objects and extracted findings in Redis."""

    SARIF_PREFIX = "sarif:"
    FINDING_PREFIX = "findings:"
    FINDING_SEEN_PREFIX = "findings_seen:"

    def __init__(self, redis: Redis):
        """Initialize the SARIF store with a Redis connection.

        Args:
            redis: Redis connection

        """
        self.redis = redis
        # Keep for backward compat with code using self.key_prefix
        self.key_prefix = self.SARIF_PREFIX

    def _get_key(self, task_id: str) -> str:
        return f"{self.SARIF_PREFIX}{task_id.lower()}"

    def _get_finding_key(self, task_id: str) -> str:
        return f"{self.FINDING_PREFIX}{task_id.lower()}"

    def _get_finding_seen_key(self, task_id: str) -> str:
        return f"{self.FINDING_SEEN_PREFIX}{task_id.lower()}"

    def _decode_key(self, key: str | bytes) -> str:
        if isinstance(key, bytes):
            return key.decode("utf-8")
        return key

    def store(self, sarif_detail: SARIFBroadcastDetail) -> None:
        """Store a SARIF broadcast detail and its extracted findings in Redis."""
        task_id = sarif_detail.task_id
        sarif_key = self._get_key(task_id)
        sarif_json = sarif_detail.model_dump_json()
        self.redis.rpush(sarif_key, sarif_json)

        findings = extract_findings(sarif_detail)
        self._store_findings(task_id, findings)

    def _store_findings(self, task_id: str, findings: list[Finding]) -> int:
        """Store findings, deduplicating by fingerprint. Returns count of new findings added."""
        finding_key = self._get_finding_key(task_id)
        seen_key = self._get_finding_seen_key(task_id)
        added = 0

        for finding in findings:
            if self.redis.sismember(seen_key, finding.fingerprint):
                continue
            self.redis.rpush(finding_key, finding.model_dump_json())
            self.redis.sadd(seen_key, finding.fingerprint)
            added += 1

        if added > 0:
            logger.info("Added %d new findings for task %s (total pool: %d)", added, task_id, added)

        return added

    def get_all(self) -> list[SARIFBroadcastDetail]:
        """Retrieve all SARIF objects from Redis."""
        all_keys = self.redis.keys(f"{self.key_prefix}*")

        result = []
        for key in all_keys:
            decoded_key = self._decode_key(key)
            sarif_list = self.redis.lrange(decoded_key, 0, -1)
            for sarif_json in sarif_list:
                sarif_detail = SARIFBroadcastDetail.model_validate_json(sarif_json)
                result.append(sarif_detail)

        return result

    def get_by_task_id(self, task_id: str) -> list[SARIFBroadcastDetail]:
        """Retrieve all SARIF objects for a specific task."""
        key = self._get_key(task_id)
        sarif_list = self.redis.lrange(key, 0, -1)

        result = []
        for sarif_json in sarif_list:
            sarif_detail = SARIFBroadcastDetail.model_validate_json(sarif_json)
            result.append(sarif_detail)

        return result

    def get_findings_by_task_id(self, task_id: str) -> list[Finding]:
        """Retrieve all findings for a specific task from the finding pool.

        Falls back to extracting from stored SARIFs if the finding pool
        is empty but SARIF data exists (backward compatibility).
        """
        finding_key = self._get_finding_key(task_id)
        finding_list = self.redis.lrange(finding_key, 0, -1)

        if finding_list:
            return [Finding.model_validate_json(f) for f in finding_list]

        # Fallback: extract from old SARIF data if present
        sarifs = self.get_by_task_id(task_id)
        if not sarifs:
            return []

        all_findings: list[Finding] = []
        for sarif_detail in sarifs:
            all_findings.extend(extract_findings(sarif_detail))

        if all_findings:
            self._store_findings(task_id, all_findings)

        return all_findings

    def delete_by_task_id(self, task_id: str) -> int:
        """Remove all SARIF objects and findings for a specific task."""
        sarif_key = self._get_key(task_id)
        finding_key = self._get_finding_key(task_id)
        seen_key = self._get_finding_seen_key(task_id)
        return self.redis.delete(sarif_key, finding_key, seen_key)
