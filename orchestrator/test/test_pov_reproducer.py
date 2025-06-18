import pytest
from unittest.mock import Mock, patch, MagicMock
from redis import Redis
from pathlib import Path

from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, POVReproduceRequest
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.maps import BuildMap
from buttercup.common.challenge_task import ChallengeTask, ReproduceResult
from buttercup.common.sets import PoVReproduceStatus
from buttercup.orchestrator.pov_reproducer.pov_reproducer import POVReproducer


@pytest.fixture
def mock_redis() -> Mock:
    """Mock Redis client for testing."""
    return Mock(spec=Redis)


@pytest.fixture
def mock_task_registry() -> Mock:
    """Mock task registry for testing."""
    registry = Mock(spec=TaskRegistry)
    registry.should_stop_processing.return_value = False
    return registry


@pytest.fixture
def mock_pov_status() -> Mock:
    """Mock PoVReproduceStatus for testing."""
    pov_status = Mock(spec=PoVReproduceStatus)
    pov_status.get_one_pending.return_value = None
    return pov_status


@pytest.fixture
def mock_node_local():
    """Mock node_local module for testing."""
    with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.node_local") as mock_nl:
        mock_nl.make_locally_available.return_value = Path("/local/pov/path")
        mock_nl.scratch_path.return_value = Path("/scratch")
        yield mock_nl


@pytest.fixture
def pov_reproducer(mock_redis: Mock, mock_task_registry: Mock, mock_pov_status: Mock) -> POVReproducer:
    """Create POVReproducer instance with mocked dependencies."""
    with (
        patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.TaskRegistry", return_value=mock_task_registry),
        patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.PoVReproduceStatus", return_value=mock_pov_status),
    ):
        reproducer = POVReproducer(redis=mock_redis, sleep_time=0.01, max_retries=3)
        return reproducer


@pytest.fixture
def sample_pov_entry() -> POVReproduceRequest:
    """Sample POVReproduceRequest for testing."""
    request = POVReproduceRequest()
    request.task_id = "test-task-123"
    request.internal_patch_id = "0/0"
    request.pov_path = "/path/to/pov.txt"
    request.sanitizer = "address"
    request.harness_name = "test_harness"
    return request


class TestPOVReproducer:
    """Test suite for POVReproducer class."""

    def test_initialization(self, mock_redis):
        """Test POVReproducer initialization."""
        with (
            patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.TaskRegistry") as mock_task_registry_class,
            patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.PoVReproduceStatus") as mock_pov_status_class,
        ):
            mock_task_registry = Mock(spec=TaskRegistry)
            mock_pov_status = Mock(spec=PoVReproduceStatus)
            mock_task_registry_class.return_value = mock_task_registry
            mock_pov_status_class.return_value = mock_pov_status

            reproducer = POVReproducer(redis=mock_redis, sleep_time=0.1, max_retries=5)

            # Verify dependencies were initialized with Redis client
            mock_task_registry_class.assert_called_once_with(mock_redis)
            mock_pov_status_class.assert_called_once_with(mock_redis)

            # Verify instance assignments and attributes
            assert reproducer.pov_status == mock_pov_status
            assert reproducer.registry == mock_task_registry
            assert reproducer.sleep_time == 0.1
            assert reproducer.max_retries == 5

    # Tests for serve_item method with current implementation
    def test_serve_item_no_pending_entries(self, pov_reproducer):
        """Test serve_item when no pending entries are available."""
        pov_reproducer.pov_status.get_one_pending.return_value = None

        result = pov_reproducer.serve_item()

        assert result is False
        pov_reproducer.pov_status.get_one_pending.assert_called_once()

    def test_serve_item_task_should_stop(self, pov_reproducer, sample_pov_entry):
        """Test serve_item when task should stop processing (cancelled/expired)."""
        pov_reproducer.pov_status.get_one_pending.return_value = sample_pov_entry
        pov_reproducer.registry.should_stop_processing.return_value = True

        result = pov_reproducer.serve_item()

        assert result is False
        pov_reproducer.registry.should_stop_processing.assert_called_once_with(sample_pov_entry.task_id)
        pov_reproducer.pov_status.mark_expired.assert_called_once_with(sample_pov_entry)

    def test_serve_item_no_build_output(self, pov_reproducer, sample_pov_entry, mock_node_local):
        """Test serve_item when no build output is available."""
        pov_reproducer.pov_status.get_one_pending.return_value = sample_pov_entry

        with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.BuildMap") as mock_build_map_class:
            mock_build_map = Mock(spec=BuildMap)
            mock_build_map.get_build_from_san.return_value = None
            mock_build_map_class.return_value = mock_build_map

            result = pov_reproducer.serve_item()

            assert result is False
            mock_build_map.get_build_from_san.assert_called_once_with(
                sample_pov_entry.task_id,
                BuildType.PATCH,
                sample_pov_entry.sanitizer,
                sample_pov_entry.internal_patch_id,
            )
            # make_locally_available should NOT be called when there's no build output
            mock_node_local.make_locally_available.assert_not_called()

    def test_serve_item_reproduce_did_not_run(self, pov_reproducer, sample_pov_entry, mock_node_local):
        """Test serve_item when reproduce_pov did not run."""
        pov_reproducer.pov_status.get_one_pending.return_value = sample_pov_entry

        # Mock BuildMap to return a valid build output
        mock_build_output = Mock(spec=BuildOutput)
        mock_build_output.task_dir = "/build/output/dir"

        with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.BuildMap") as mock_build_map_class:
            mock_build_map = Mock(spec=BuildMap)
            mock_build_map.get_build_from_san.return_value = mock_build_output
            mock_build_map_class.return_value = mock_build_map

            # Mock ChallengeTask reproduction that didn't run
            with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.ChallengeTask") as mock_task_class:
                mock_challenge_task = Mock(spec=ChallengeTask)
                mock_task_class.return_value = mock_challenge_task

                # Mock task reproduction context manager
                mock_rw_task = Mock()
                mock_reproduce_result = Mock(spec=ReproduceResult)
                mock_reproduce_result.did_run.return_value = False  # Reproduction did not run
                mock_rw_task.reproduce_pov.return_value = mock_reproduce_result

                # Use MagicMock for context manager
                mock_context_manager = MagicMock()
                mock_context_manager.__enter__.return_value = mock_rw_task
                mock_challenge_task.get_rw_copy.return_value = mock_context_manager

                result = pov_reproducer.serve_item()

                assert result is False
                # Verify no status was marked since reproduction didn't run
                pov_reproducer.pov_status.mark_mitigated.assert_not_called()
                pov_reproducer.pov_status.mark_non_mitigated.assert_not_called()

    def test_serve_item_exception_handling(self, pov_reproducer, sample_pov_entry, mock_node_local):
        """Test serve_item handles exceptions gracefully."""
        pov_reproducer.pov_status.get_one_pending.return_value = sample_pov_entry

        # Mock BuildMap to raise an exception
        with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.BuildMap") as mock_build_map_class:
            mock_build_map_class.side_effect = Exception("BuildMap failed")

            # The exception should propagate since there's no try-catch in the implementation
            with pytest.raises(Exception, match="BuildMap failed"):
                pov_reproducer.serve_item()

    @patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.serve_loop")
    @patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.logger")
    def test_serve(self, mock_logger, mock_serve_loop, pov_reproducer):
        """Test serve method starts the serve loop correctly."""
        pov_reproducer.serve()

        mock_logger.info.assert_called_once_with("Starting POV Reproducer")
        mock_serve_loop.assert_called_once_with(pov_reproducer.serve_item, pov_reproducer.sleep_time)

    def test_custom_max_retries(self, mock_redis):
        """Test POVReproducer initialization with custom max_retries."""
        with (
            patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.TaskRegistry"),
            patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.PoVReproduceStatus"),
        ):
            reproducer = POVReproducer(redis=mock_redis, max_retries=15)
            assert reproducer.max_retries == 15

    def test_serve_item_successful_reproduction_crashed(self, pov_reproducer, sample_pov_entry, mock_node_local):
        """Test serve_item successful reproduction where POV crashed (not mitigated)."""
        pov_reproducer.pov_status.get_one_pending.return_value = sample_pov_entry

        # Mock BuildMap to return a valid build output
        mock_build_output = Mock(spec=BuildOutput)
        mock_build_output.task_dir = "/build/output/dir"

        with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.BuildMap") as mock_build_map_class:
            mock_build_map = Mock(spec=BuildMap)
            mock_build_map.get_build_from_san.return_value = mock_build_output
            mock_build_map_class.return_value = mock_build_map

            # Mock ChallengeTask reproduction
            with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.ChallengeTask") as mock_task_class:
                mock_challenge_task = Mock(spec=ChallengeTask)
                mock_task_class.return_value = mock_challenge_task

                # Mock task reproduction context manager
                mock_rw_task = Mock()
                mock_reproduce_result = Mock(spec=ReproduceResult)
                mock_reproduce_result.did_run.return_value = True
                mock_reproduce_result.did_crash.return_value = True  # POV crashed (not mitigated)
                # Add command_result for logging
                mock_command_result = Mock()
                mock_command_result.output = "test stdout output"
                mock_command_result.error = "test stderr output"
                mock_reproduce_result.command_result = mock_command_result
                mock_rw_task.reproduce_pov.return_value = mock_reproduce_result

                # Use MagicMock for context manager
                mock_context_manager = MagicMock()
                mock_context_manager.__enter__.return_value = mock_rw_task
                mock_challenge_task.get_rw_copy.return_value = mock_context_manager

                result = pov_reproducer.serve_item()

                assert result is True
                # Verify POV was marked as non-mitigated
                pov_reproducer.pov_status.mark_non_mitigated.assert_called_once_with(sample_pov_entry)

    def test_serve_item_successful_reproduction_no_crash(self, pov_reproducer, sample_pov_entry, mock_node_local):
        """Test serve_item successful reproduction where POV did not crash (mitigated)."""
        pov_reproducer.pov_status.get_one_pending.return_value = sample_pov_entry

        # Mock BuildMap to return a valid build output
        mock_build_output = Mock(spec=BuildOutput)
        mock_build_output.task_dir = "/build/output/dir"

        with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.BuildMap") as mock_build_map_class:
            mock_build_map = Mock(spec=BuildMap)
            mock_build_map.get_build_from_san.return_value = mock_build_output
            mock_build_map_class.return_value = mock_build_map

            # Mock ChallengeTask reproduction
            with patch("buttercup.orchestrator.pov_reproducer.pov_reproducer.ChallengeTask") as mock_task_class:
                mock_challenge_task = Mock(spec=ChallengeTask)
                mock_task_class.return_value = mock_challenge_task

                # Mock task reproduction context manager
                mock_rw_task = Mock()
                mock_reproduce_result = Mock(spec=ReproduceResult)
                mock_reproduce_result.did_run.return_value = True
                mock_reproduce_result.did_crash.return_value = False  # POV did not crash (mitigated)
                # Add command_result for logging
                mock_command_result = Mock()
                mock_command_result.output = "test stdout output"
                mock_command_result.error = "test stderr output"
                mock_reproduce_result.command_result = mock_command_result
                mock_rw_task.reproduce_pov.return_value = mock_reproduce_result

                # Use MagicMock for context manager
                mock_context_manager = MagicMock()
                mock_context_manager.__enter__.return_value = mock_rw_task
                mock_challenge_task.get_rw_copy.return_value = mock_context_manager

                result = pov_reproducer.serve_item()

                assert result is True
                # Verify POV was marked as mitigated
                pov_reproducer.pov_status.mark_mitigated.assert_called_once_with(sample_pov_entry)
