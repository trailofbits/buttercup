import json

import pytest
from redis import Redis

from buttercup.common.sarif_store import (
    Finding,
    SARIFBroadcastDetail,
    SARIFStore,
    extract_findings,
)


@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=9)


@pytest.fixture
def sarif_store(redis_client):
    store = SARIFStore(redis_client)

    # Clean any existing test data across all key namespaces
    for prefix in (SARIFStore.SARIF_PREFIX, SARIFStore.FINDING_PREFIX, SARIFStore.FINDING_SEEN_PREFIX):
        for key in redis_client.keys(f"{prefix}*"):
            redis_client.delete(key)

    yield store

    for prefix in (SARIFStore.SARIF_PREFIX, SARIFStore.FINDING_PREFIX, SARIFStore.FINDING_SEEN_PREFIX):
        for key in redis_client.keys(f"{prefix}*"):
            redis_client.delete(key)


@pytest.fixture
def sample_sarif_detail():
    """Create a sample SARIFBroadcastDetail for testing"""
    return SARIFBroadcastDetail(
        metadata={"source": "test", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id",
        task_id="test-task-id",
    )


@pytest.fixture
def sarif_with_findings():
    """Create a SARIFBroadcastDetail with realistic findings."""
    return SARIFBroadcastDetail(
        metadata={"source": "test"},
        sarif={
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "CodeScan++"}},
                    "results": [
                        {
                            "ruleId": "CWE-121",
                            "level": "error",
                            "message": {"text": "Stack-based buffer overflow"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "pngrutil.c"},
                                        "region": {"startLine": 1421, "endLine": 1447},
                                    },
                                },
                            ],
                        },
                        {
                            "ruleId": "CWE-787",
                            "level": "warning",
                            "message": {"text": "Out-of-bounds write"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "pngread.c"},
                                        "region": {"startLine": 200, "endLine": 210, "startColumn": 5},
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        sarif_id="sarif-with-findings",
        task_id="test-task-id",
    )


def test_sarif_store_store_and_get_by_task_id(sarif_store, sample_sarif_detail):
    """Test storing a SARIF detail and retrieving it by task ID"""
    sarif_store.store(sample_sarif_detail)
    retrieved_sarifs = sarif_store.get_by_task_id(sample_sarif_detail.task_id)

    assert len(retrieved_sarifs) == 1
    retrieved = retrieved_sarifs[0]
    assert retrieved.sarif_id == sample_sarif_detail.sarif_id
    assert retrieved.task_id == sample_sarif_detail.task_id
    assert retrieved.metadata == sample_sarif_detail.metadata
    assert retrieved.sarif == sample_sarif_detail.sarif


def test_sarif_store_get_all(sarif_store, sample_sarif_detail):
    """Test retrieving all SARIF details"""
    second_sarif = SARIFBroadcastDetail(
        metadata={"source": "test2", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id-2",
        task_id="test-task-id-2",
    )

    sarif_store.store(sample_sarif_detail)
    sarif_store.store(second_sarif)

    all_sarifs = sarif_store.get_all()
    assert len(all_sarifs) == 2

    task_ids = {sarif.task_id for sarif in all_sarifs}
    assert sample_sarif_detail.task_id in task_ids
    assert second_sarif.task_id in task_ids


def test_sarif_store_multiple_sarifs_per_task(sarif_store, sample_sarif_detail):
    """Test storing multiple SARIF details for the same task"""
    second_sarif = SARIFBroadcastDetail(
        metadata={"source": "test2", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id-2",
        task_id=sample_sarif_detail.task_id,
    )

    sarif_store.store(sample_sarif_detail)
    sarif_store.store(second_sarif)

    retrieved_sarifs = sarif_store.get_by_task_id(sample_sarif_detail.task_id)
    assert len(retrieved_sarifs) == 2

    sarif_ids = {sarif.sarif_id for sarif in retrieved_sarifs}
    assert sample_sarif_detail.sarif_id in sarif_ids
    assert second_sarif.sarif_id in sarif_ids


def test_sarif_store_delete_by_task_id(sarif_store, sample_sarif_detail):
    """Test deleting SARIF details by task ID"""
    second_sarif = SARIFBroadcastDetail(
        metadata={"source": "test2", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id-2",
        task_id="test-task-id-2",
    )

    sarif_store.store(sample_sarif_detail)
    sarif_store.store(second_sarif)

    deleted = sarif_store.delete_by_task_id(sample_sarif_detail.task_id)
    assert deleted >= 1

    all_sarifs = sarif_store.get_all()
    assert len(all_sarifs) == 1
    assert all_sarifs[0].task_id == second_sarif.task_id


def test_sarif_store_nonexistent_task_id(sarif_store):
    """Test retrieving and deleting SARIF details for a nonexistent task ID"""
    retrieved_sarifs = sarif_store.get_by_task_id("nonexistent-task-id")
    assert retrieved_sarifs == []

    deleted = sarif_store.delete_by_task_id("nonexistent-task-id")
    assert deleted == 0


def test_sarif_store_case_insensitive_task_id(sarif_store, sample_sarif_detail):
    """Test that task IDs are case-insensitive"""
    lowercase_task_id = sample_sarif_detail.task_id.lower()
    sample_sarif_detail.task_id = lowercase_task_id
    sarif_store.store(sample_sarif_detail)

    uppercase_task_id = lowercase_task_id.upper()
    retrieved_sarifs = sarif_store.get_by_task_id(uppercase_task_id)

    assert len(retrieved_sarifs) == 1
    assert retrieved_sarifs[0].sarif_id == sample_sarif_detail.sarif_id


def test_sarif_store_json_serialization(sarif_store, sample_sarif_detail):
    """Test that SARIF details are properly serialized and deserialized"""
    sarif_store.store(sample_sarif_detail)

    key = sarif_store._get_key(sample_sarif_detail.task_id)
    raw_json = sarif_store.redis.lrange(key, 0, -1)[0]

    parsed_json = json.loads(raw_json)
    assert parsed_json["sarif_id"] == sample_sarif_detail.sarif_id
    assert parsed_json["task_id"] == sample_sarif_detail.task_id
    assert parsed_json["metadata"] == sample_sarif_detail.metadata
    assert parsed_json["sarif"] == sample_sarif_detail.sarif


# --- Finding pool tests ---


def test_extract_findings(sarif_with_findings):
    """Test extracting individual findings from SARIF broadcast detail."""
    findings = extract_findings(sarif_with_findings)

    assert len(findings) == 2

    f0 = findings[0]
    assert f0.rule_id == "CWE-121"
    assert f0.level == "error"
    assert f0.message == "Stack-based buffer overflow"
    assert f0.file_uri == "pngrutil.c"
    assert f0.start_line == 1421
    assert f0.end_line == 1447
    assert f0.start_column is None
    assert f0.tool_name == "CodeScan++"
    assert f0.sarif_id == "sarif-with-findings"

    f1 = findings[1]
    assert f1.rule_id == "CWE-787"
    assert f1.file_uri == "pngread.c"
    assert f1.start_column == 5


def test_extract_findings_skips_malformed_results():
    """Test that extraction skips results without locations or file URIs."""
    detail = SARIFBroadcastDetail(
        metadata={},
        sarif={
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "TestTool"}},
                    "results": [
                        {"ruleId": "R1", "level": "error", "message": {"text": "no locations"}},
                        {
                            "ruleId": "R2",
                            "level": "error",
                            "message": {"text": "no file uri"},
                            "locations": [{"physicalLocation": {"artifactLocation": {}}}],
                        },
                        {
                            "ruleId": "R3",
                            "level": "error",
                            "message": {"text": "no start line"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "test.c"},
                                        "region": {},
                                    },
                                },
                            ],
                        },
                        {
                            "ruleId": "R4",
                            "level": "warning",
                            "message": {"text": "valid"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "good.c"},
                                        "region": {"startLine": 10},
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        sarif_id="malformed-test",
        task_id="task-1",
    )

    findings = extract_findings(detail)
    assert len(findings) == 1
    assert findings[0].rule_id == "R4"
    assert findings[0].end_line == 10  # defaults to start_line


def test_extract_findings_empty_runs():
    """Test extraction from SARIF with no runs."""
    detail = SARIFBroadcastDetail(
        metadata={},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="empty",
        task_id="task-1",
    )
    assert extract_findings(detail) == []


def test_store_populates_findings(sarif_store, sarif_with_findings):
    """Test that store() populates both sarif and findings keys."""
    sarif_store.store(sarif_with_findings)

    # SARIF key should have the full broadcast
    sarifs = sarif_store.get_by_task_id("test-task-id")
    assert len(sarifs) == 1

    # Findings key should have extracted findings
    findings = sarif_store.get_findings_by_task_id("test-task-id")
    assert len(findings) == 2
    assert findings[0].rule_id == "CWE-121"
    assert findings[1].rule_id == "CWE-787"


def test_findings_deduplication(sarif_store, sarif_with_findings):
    """Test that storing the same SARIF twice doesn't duplicate findings."""
    sarif_store.store(sarif_with_findings)
    sarif_store.store(sarif_with_findings)

    findings = sarif_store.get_findings_by_task_id("test-task-id")
    assert len(findings) == 2  # Not 4


def test_findings_backward_compat_fallback(sarif_store, sarif_with_findings):
    """Test fallback extraction when only sarif: keys exist."""
    # Manually store only the SARIF (bypassing finding extraction)
    task_id = sarif_with_findings.task_id
    sarif_key = sarif_store._get_key(task_id)
    sarif_store.redis.rpush(sarif_key, sarif_with_findings.model_dump_json())

    # get_findings_by_task_id should extract on the fly
    findings = sarif_store.get_findings_by_task_id(task_id)
    assert len(findings) == 2
    assert findings[0].rule_id == "CWE-121"

    # After fallback, findings should now be stored
    finding_key = sarif_store._get_finding_key(task_id)
    assert sarif_store.redis.llen(finding_key) == 2


def test_delete_cleans_all_keys(sarif_store, sarif_with_findings):
    """Test that delete_by_task_id removes sarif, findings, and seen keys."""
    sarif_store.store(sarif_with_findings)
    task_id = sarif_with_findings.task_id

    # Verify keys exist
    assert sarif_store.redis.llen(sarif_store._get_key(task_id)) > 0
    assert sarif_store.redis.llen(sarif_store._get_finding_key(task_id)) > 0
    assert sarif_store.redis.scard(sarif_store._get_finding_seen_key(task_id)) > 0

    sarif_store.delete_by_task_id(task_id)

    assert sarif_store.redis.llen(sarif_store._get_key(task_id)) == 0
    assert sarif_store.redis.llen(sarif_store._get_finding_key(task_id)) == 0
    assert sarif_store.redis.scard(sarif_store._get_finding_seen_key(task_id)) == 0


def test_finding_fingerprint():
    """Test finding fingerprint generation."""
    finding = Finding(
        rule_id="CWE-121",
        level="error",
        message="test",
        file_uri="foo.c",
        start_line=10,
        end_line=20,
        tool_name="T",
        sarif_id="s1",
        task_id="t1",
    )
    assert finding.fingerprint == "CWE-121:foo.c:10:20"


def test_get_findings_nonexistent_task(sarif_store):
    """Test getting findings for a task with no data."""
    findings = sarif_store.get_findings_by_task_id("nonexistent")
    assert findings == []
