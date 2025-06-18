import unittest
from unittest.mock import Mock, patch, MagicMock
from redis import Redis
from pathlib import Path

from buttercup.fuzzing_infra.builder_bot import BuilderBot
from buttercup.common.datastructures.msg_pb2 import BuildRequest, BuildOutput, BuildType
from buttercup.common.task_registry import TaskRegistry


class TestBuilderBot(unittest.TestCase):
    def setUp(self):
        self.redis_mock = Mock(spec=Redis)
        self.seconds_sleep = 1.0
        self.allow_caching = True
        self.allow_pull = True
        self.python = "/usr/bin/python3"
        self.wdir = "/tmp/test_wdir"

        # Mock queue factory and queues
        self.queue_factory_mock = Mock()
        self.build_requests_queue_mock = Mock()
        self.build_outputs_queue_mock = Mock()

        self.queue_factory_mock.create.side_effect = [self.build_requests_queue_mock, self.build_outputs_queue_mock]
        self.task_registry_mock = MagicMock(spec=TaskRegistry)
        self.task_registry_mock.should_stop_processing.return_value = False

        # Create BuilderBot instance with mocked dependencies
        with (
            patch("buttercup.fuzzing_infra.builder_bot.QueueFactory") as queue_factory_class_mock,
            patch("buttercup.fuzzing_infra.builder_bot.TaskRegistry") as task_registry_class_mock,
        ):
            queue_factory_class_mock.return_value = self.queue_factory_mock
            task_registry_class_mock.return_value = self.task_registry_mock
            self.builder_bot = BuilderBot(
                redis=self.redis_mock,
                seconds_sleep=self.seconds_sleep,
                allow_caching=self.allow_caching,
                allow_pull=self.allow_pull,
                python=self.python,
                wdir=self.wdir,
            )

    def test_post_init_sets_up_queues(self):
        """Test that __post_init__ correctly sets up the queues."""
        # Verify that the queues were created with correct parameters
        self.assertEqual(self.builder_bot._build_requests_queue, self.build_requests_queue_mock)
        self.assertEqual(self.builder_bot._build_outputs_queue, self.build_outputs_queue_mock)
        self.assertEqual(self.queue_factory_mock.create.call_count, 2)

    def test_apply_challenge_diff_no_diff(self):
        """Test _apply_challenge_diff when no diff is requested."""
        task_mock = Mock()
        msg = BuildRequest(apply_diff=False)

        result = self.builder_bot._apply_challenge_diff(task_mock, msg)

        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_not_called()

    def test_apply_challenge_diff_with_diff_success(self):
        """Test _apply_challenge_diff when diff is requested and succeeds."""
        task_mock = Mock()
        task_mock.apply_patch_diff.return_value = True
        msg = BuildRequest(apply_diff=True)

        result = self.builder_bot._apply_challenge_diff(task_mock, msg)

        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_called_once()

    def test_apply_challenge_diff_with_diff_failure(self):
        """Test _apply_challenge_diff when diff is requested but fails."""
        task_mock = Mock()
        task_mock.apply_patch_diff.return_value = False
        msg = BuildRequest(apply_diff=True)

        result = self.builder_bot._apply_challenge_diff(task_mock, msg)

        self.assertFalse(result)
        task_mock.apply_patch_diff.assert_called_once()

    def test_apply_patch_no_patch(self):
        """Test _apply_patch when no patch is provided."""
        task_mock = Mock()
        msg = BuildRequest(patch="")

        result = self.builder_bot._apply_patch(task_mock, msg)

        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_not_called()

    @patch("tempfile.NamedTemporaryFile")
    def test_apply_patch_with_patch_success(self, temp_file_mock):
        """Test _apply_patch when patch is provided and succeeds."""
        task_mock = Mock()
        task_mock.apply_patch_diff.return_value = True

        patch_content = "--- a/file.c\n+++ b/file.c\n@@ -1,3 +1,3 @@\n-old line\n+new line"
        msg = BuildRequest(patch=patch_content, internal_patch_id="123")

        # Mock the temporary file
        temp_file_instance = MagicMock()
        temp_file_instance.name = "/tmp/test_patch_file"
        temp_file_mock.return_value.__enter__.return_value = temp_file_instance

        result = self.builder_bot._apply_patch(task_mock, msg)

        self.assertTrue(result)
        temp_file_instance.write.assert_called_once_with(patch_content)
        temp_file_instance.flush.assert_called_once()
        task_mock.apply_patch_diff.assert_called_once_with(Path("/tmp/test_patch_file"))

    @patch("tempfile.NamedTemporaryFile")
    def test_apply_patch_with_patch_failure(self, temp_file_mock):
        """Test _apply_patch when patch is provided but fails to apply."""
        task_mock = Mock()
        task_mock.apply_patch_diff.return_value = False

        patch_content = "--- a/file.c\n+++ b/file.c\n@@ -1,3 +1,3 @@\n-old line\n+new line"
        msg = BuildRequest(patch=patch_content, internal_patch_id="123")

        # Mock the temporary file
        temp_file_instance = MagicMock()
        temp_file_instance.name = "/tmp/test_patch_file"
        temp_file_mock.return_value.__enter__.return_value = temp_file_instance

        result = self.builder_bot._apply_patch(task_mock, msg)

        self.assertFalse(result)
        temp_file_instance.write.assert_called_once_with(patch_content)
        temp_file_instance.flush.assert_called_once()
        task_mock.apply_patch_diff.assert_called_once_with(Path("/tmp/test_patch_file"))

    def test_serve_item_no_item_in_queue(self):
        """Test serve_item when there's no item in the queue."""
        self.build_requests_queue_mock.pop.return_value = None

        result = self.builder_bot.serve_item()

        self.assertFalse(result)
        self.build_requests_queue_mock.pop.assert_called_once()

    @patch("buttercup.fuzzing_infra.builder_bot.ChallengeTask")
    @patch("buttercup.fuzzing_infra.builder_bot.node_local.dir_to_remote_archive")
    @patch("buttercup.fuzzing_infra.builder_bot.trace")
    def test_serve_item_successful_build_with_caching(self, trace_mock, dir_to_remote_mock, challenge_task_mock):
        """Test serve_item with successful build when caching is enabled."""
        # Setup queue item mock
        queue_item_mock = Mock()
        queue_item_mock.item_id = "test_item_id"
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="libfuzzer",
            sanitizer="address",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=False,
            patch="",
            internal_patch_id="",
        )
        self.build_requests_queue_mock.pop.return_value = queue_item_mock

        # Setup challenge task mocks
        origin_task_mock = Mock()
        origin_task_mock.task_meta.metadata = {"key": "value"}  # Mock metadata as dict
        task_mock = Mock()
        task_mock.task_dir = Path("/tmp/test_task_dir")

        # Mock build result
        build_result_mock = Mock()
        build_result_mock.success = True
        task_mock.build_fuzzers_with_cache.return_value = build_result_mock

        # Setup context manager for get_rw_copy
        context_manager_mock = MagicMock()
        context_manager_mock.__enter__.return_value = task_mock
        context_manager_mock.__exit__.return_value = None
        origin_task_mock.get_rw_copy.return_value = context_manager_mock
        challenge_task_mock.return_value = origin_task_mock

        # Setup tracer mock
        tracer_mock = Mock()
        span_mock = Mock()
        span_context_manager_mock = MagicMock()
        span_context_manager_mock.__enter__.return_value = span_mock
        span_context_manager_mock.__exit__.return_value = None
        tracer_mock.start_as_current_span.return_value = span_context_manager_mock
        trace_mock.get_tracer.return_value = tracer_mock

        # Call serve_item
        result = self.builder_bot.serve_item()

        # Verify behavior
        self.assertTrue(result)

        # Verify ChallengeTask was created with caching enabled
        challenge_task_mock.assert_called_once_with(
            Path("/path/to/task"), python_path=self.python, local_task_dir=Path("/path/to/task")
        )

        # Verify build was called
        task_mock.build_fuzzers_with_cache.assert_called_once_with(
            engine="libfuzzer", sanitizer="address", pull_latest_base_image=self.allow_pull
        )

        # Verify task was committed and archived
        task_mock.commit.assert_called_once()
        dir_to_remote_mock.assert_called_once_with(task_mock.task_dir)

        # Verify build output was pushed with correct message
        build_output_call = self.build_outputs_queue_mock.push.call_args[0][0]
        self.assertIsInstance(build_output_call, BuildOutput)
        self.assertEqual(build_output_call.task_id, "test_task")
        self.assertEqual(build_output_call.engine, "libfuzzer")
        self.assertEqual(build_output_call.sanitizer, "address")
        self.assertEqual(build_output_call.build_type, BuildType.FUZZER)
        self.assertEqual(build_output_call.task_dir, "/tmp/test_task_dir")
        self.assertEqual(build_output_call.internal_patch_id, "")

        # Verify item was acked
        self.build_requests_queue_mock.ack_item.assert_called_once_with("test_item_id")

    @patch("buttercup.fuzzing_infra.builder_bot.ChallengeTask")
    @patch("buttercup.fuzzing_infra.builder_bot.node_local.dir_to_remote_archive")
    @patch("buttercup.fuzzing_infra.builder_bot.trace")
    def test_serve_item_successful_build_without_caching(self, trace_mock, dir_to_remote_mock, challenge_task_mock):
        """Test serve_item with successful build when caching is disabled."""
        # Disable caching for this test
        self.builder_bot.allow_caching = False

        # Setup queue item mock
        queue_item_mock = Mock()
        queue_item_mock.item_id = "test_item_id"
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="libfuzzer",
            sanitizer="address",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=False,
        )
        self.build_requests_queue_mock.pop.return_value = queue_item_mock

        # Setup challenge task mocks
        origin_task_mock = Mock()
        origin_task_mock.task_meta.metadata = {"key": "value"}  # Mock metadata as dict
        task_mock = Mock()
        task_mock.task_dir = Path("/tmp/test_task_dir")

        # Mock build result
        build_result_mock = Mock()
        build_result_mock.success = True
        task_mock.build_fuzzers_with_cache.return_value = build_result_mock

        # Setup context manager for get_rw_copy
        context_manager_mock = MagicMock()
        context_manager_mock.__enter__.return_value = task_mock
        context_manager_mock.__exit__.return_value = None
        origin_task_mock.get_rw_copy.return_value = context_manager_mock
        challenge_task_mock.return_value = origin_task_mock

        # Setup tracer mock
        tracer_mock = Mock()
        span_mock = Mock()
        span_context_manager_mock = MagicMock()
        span_context_manager_mock.__enter__.return_value = span_mock
        span_context_manager_mock.__exit__.return_value = None
        tracer_mock.start_as_current_span.return_value = span_context_manager_mock
        trace_mock.get_tracer.return_value = tracer_mock

        # Call serve_item
        result = self.builder_bot.serve_item()

        # Verify behavior
        self.assertTrue(result)

        # Verify ChallengeTask was created without caching
        challenge_task_mock.assert_called_once_with(Path("/path/to/task"), python_path=self.python)

        # Verify build was called
        task_mock.build_fuzzers_with_cache.assert_called_once_with(
            engine="libfuzzer", sanitizer="address", pull_latest_base_image=self.allow_pull
        )

        # Verify task was committed and archived
        task_mock.commit.assert_called_once()
        dir_to_remote_mock.assert_called_once_with(task_mock.task_dir)

        # Verify build output was pushed
        self.build_outputs_queue_mock.push.assert_called_once()

        # Verify item was acked
        self.build_requests_queue_mock.ack_item.assert_called_once_with("test_item_id")

    @patch("buttercup.fuzzing_infra.builder_bot.ChallengeTask")
    @patch("buttercup.fuzzing_infra.builder_bot.trace")
    def test_serve_item_build_failure(self, trace_mock, challenge_task_mock):
        """Test serve_item when build fails."""
        # Setup queue item mock
        queue_item_mock = Mock()
        queue_item_mock.item_id = "test_item_id"
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="libfuzzer",
            sanitizer="address",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=False,
            patch="",
            internal_patch_id="",
        )
        self.build_requests_queue_mock.pop.return_value = queue_item_mock

        # Setup challenge task mocks
        origin_task_mock = Mock()
        origin_task_mock.task_meta.metadata = {"key": "value"}  # Mock metadata as dict
        task_mock = Mock()

        # Mock build result failure
        build_result_mock = Mock()
        build_result_mock.success = False
        task_mock.build_fuzzers_with_cache.return_value = build_result_mock

        # Setup context manager for get_rw_copy
        context_manager_mock = MagicMock()
        context_manager_mock.__enter__.return_value = task_mock
        context_manager_mock.__exit__.return_value = None
        origin_task_mock.get_rw_copy.return_value = context_manager_mock
        challenge_task_mock.return_value = origin_task_mock

        # Setup tracer mock
        tracer_mock = Mock()
        span_mock = Mock()
        span_context_manager_mock = MagicMock()
        span_context_manager_mock.__enter__.return_value = span_mock
        span_context_manager_mock.__exit__.return_value = None
        tracer_mock.start_as_current_span.return_value = span_context_manager_mock
        trace_mock.get_tracer.return_value = tracer_mock

        # Call serve_item
        result = self.builder_bot.serve_item()

        # Verify behavior
        self.assertTrue(result)  # Should still return True to continue processing

        # Verify build was attempted
        task_mock.build_fuzzers_with_cache.assert_called_once()

        # Verify task was NOT committed (build failed)
        task_mock.commit.assert_not_called()

        # Verify build output was NOT pushed
        self.build_outputs_queue_mock.push.assert_not_called()

        # Verify span was marked as error
        span_mock.set_status.assert_called()

    @patch("buttercup.fuzzing_infra.builder_bot.ChallengeTask")
    def test_serve_item_patch_application_failure(self, challenge_task_mock):
        """Test serve_item when patch application fails."""
        # Setup queue item mock with a patch that will fail
        queue_item_mock = Mock()
        queue_item_mock.item_id = "test_item_id"
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="libfuzzer",
            sanitizer="address",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=False,
            patch="some patch content",
            internal_patch_id="",
        )
        self.build_requests_queue_mock.pop.return_value = queue_item_mock

        # Setup challenge task mocks
        origin_task_mock = Mock()
        origin_task_mock.task_meta.metadata = {"key": "value"}  # Mock metadata as dict
        task_mock = Mock()
        task_mock.apply_patch_diff.return_value = False  # Patch application fails

        # Setup context manager for get_rw_copy
        context_manager_mock = MagicMock()
        context_manager_mock.__enter__.return_value = task_mock
        context_manager_mock.__exit__.return_value = None
        origin_task_mock.get_rw_copy.return_value = context_manager_mock
        challenge_task_mock.return_value = origin_task_mock

        # Mock times_delivered to return a value that exceeds max_tries
        self.build_requests_queue_mock.times_delivered.return_value = 4

        # Mock the _apply_patch method to return False
        with patch.object(self.builder_bot, "_apply_patch", return_value=False):
            # Call serve_item
            result = self.builder_bot.serve_item()

        # Verify behavior
        self.assertTrue(result)  # Should still return True to continue processing

        # Verify build was NOT attempted (patch failed)
        task_mock.build_fuzzers_with_cache.assert_not_called()

        # Verify item was acked to avoid retrying forever
        self.build_requests_queue_mock.ack_item.assert_called_once_with("test_item_id")

    @patch("buttercup.fuzzing_infra.builder_bot.serve_loop")
    def test_run(self, serve_loop_mock):
        """Test the run method."""
        self.builder_bot.run()

        # Verify serve_loop was called with correct parameters
        serve_loop_mock.assert_called_once_with(self.builder_bot.serve_item, self.seconds_sleep)

    @patch("buttercup.fuzzing_infra.builder_bot.ChallengeTask")
    @patch("buttercup.fuzzing_infra.builder_bot.node_local.dir_to_remote_archive")
    @patch("buttercup.fuzzing_infra.builder_bot.trace")
    def test_serve_item_with_diff_and_patch(self, trace_mock, dir_to_remote_mock, challenge_task_mock):
        """Test serve_item with both diff and patch applied."""
        # Setup queue item mock
        queue_item_mock = Mock()
        queue_item_mock.item_id = "test_item_id"
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="libfuzzer",
            sanitizer="address",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=True,
            patch="some patch content",
            internal_patch_id="patch123",
        )
        self.build_requests_queue_mock.pop.return_value = queue_item_mock

        # Setup challenge task mocks
        origin_task_mock = Mock()
        origin_task_mock.task_meta.metadata = {"key": "value"}  # Mock metadata as dict
        task_mock = Mock()
        task_mock.task_dir = Path("/tmp/test_task_dir")
        task_mock.apply_patch_diff.return_value = True  # Both diff and patch succeed

        # Mock build result
        build_result_mock = Mock()
        build_result_mock.success = True
        task_mock.build_fuzzers_with_cache.return_value = build_result_mock

        # Setup context manager for get_rw_copy
        context_manager_mock = MagicMock()
        context_manager_mock.__enter__.return_value = task_mock
        context_manager_mock.__exit__.return_value = None
        origin_task_mock.get_rw_copy.return_value = context_manager_mock
        challenge_task_mock.return_value = origin_task_mock

        # Setup tracer mock
        tracer_mock = Mock()
        span_mock = Mock()
        span_context_manager_mock = MagicMock()
        span_context_manager_mock.__enter__.return_value = span_mock
        span_context_manager_mock.__exit__.return_value = None
        tracer_mock.start_as_current_span.return_value = span_context_manager_mock
        trace_mock.get_tracer.return_value = tracer_mock

        # Call serve_item
        result = self.builder_bot.serve_item()

        # Verify behavior
        self.assertTrue(result)

        # Verify both diff and patch were applied
        # apply_patch_diff should be called twice: once for diff, once for patch
        self.assertEqual(task_mock.apply_patch_diff.call_count, 2)

        # Verify build was successful
        task_mock.build_fuzzers_with_cache.assert_called_once()
        task_mock.commit.assert_called_once()

        # Verify build output includes internal_patch_id
        build_output_call = self.build_outputs_queue_mock.push.call_args[0][0]
        self.assertEqual(build_output_call.internal_patch_id, "patch123")

    @patch("buttercup.fuzzing_infra.builder_bot.ChallengeTask")
    def test_max_tries_for_diff_and_patch(self, challenge_task_mock):
        """Test that max_tries is respected for both diff and patch application failures."""
        # Test 1: Diff application failure - times_delivered < max_tries (should NOT ack)
        queue_item_mock = Mock()
        queue_item_mock.item_id = "test_item_id"
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="test_engine",
            sanitizer="test_sanitizer",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=True,
            patch="",  # No patch for this test
            internal_patch_id="",
        )
        self.build_requests_queue_mock.pop.return_value = queue_item_mock

        # Setup challenge task mocks
        origin_task_mock = Mock()
        origin_task_mock.task_meta.metadata = {"key": "value"}  # Mock metadata as dict
        task_mock = Mock()
        task_mock.task_dir = Path("/tmp/test_task_dir")

        # Diff always fails
        task_mock.apply_patch_diff.return_value = False

        # Setup context manager for get_rw_copy
        context_manager_mock = MagicMock()
        context_manager_mock.__enter__.return_value = task_mock
        context_manager_mock.__exit__.return_value = None
        origin_task_mock.get_rw_copy.return_value = context_manager_mock
        challenge_task_mock.return_value = origin_task_mock

        # Mock times_delivered to simulate NOT exceeding max_tries (max_tries=3, so 2 should not ack)
        self.build_requests_queue_mock.times_delivered.return_value = 2

        # Call serve_item - should NOT ack because max tries not exceeded
        result = self.builder_bot.serve_item()
        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_called_once()
        self.build_requests_queue_mock.ack_item.assert_not_called()

        # Test 2: Diff application failure - times_delivered > max_tries (should ack)
        self.build_requests_queue_mock.reset_mock()
        task_mock.reset_mock()

        # Mock times_delivered to simulate exceeding max_tries
        self.build_requests_queue_mock.times_delivered.return_value = 4

        # Call serve_item - should ack because max tries exceeded
        result = self.builder_bot.serve_item()
        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_called_once()
        self.build_requests_queue_mock.ack_item.assert_called_once_with("test_item_id")

        # Test 3: Patch application failure - times_delivered < max_tries (should NOT ack)
        self.build_requests_queue_mock.reset_mock()
        task_mock.reset_mock()

        # New queue item with patch
        queue_item_mock.deserialized = BuildRequest(
            task_id="test_task",
            engine="test_engine",
            sanitizer="test_sanitizer",
            build_type=BuildType.FUZZER,
            task_dir="/path/to/task",
            apply_diff=False,  # No diff for this test
            patch="some patch content",
            internal_patch_id="patch123",
        )

        # Patch always fails
        task_mock.apply_patch_diff.return_value = False

        # Mock times_delivered to simulate NOT exceeding max_tries
        self.build_requests_queue_mock.times_delivered.return_value = 2

        # Call serve_item - should NOT ack because max tries not exceeded
        result = self.builder_bot.serve_item()
        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_called_once()
        self.build_requests_queue_mock.ack_item.assert_not_called()

        # Test 4: Patch application failure - times_delivered > max_tries (should ack)
        self.build_requests_queue_mock.reset_mock()
        task_mock.reset_mock()

        # Mock times_delivered to simulate exceeding max_tries
        self.build_requests_queue_mock.times_delivered.return_value = 4

        # Call serve_item - should ack because max tries exceeded
        result = self.builder_bot.serve_item()
        self.assertTrue(result)
        task_mock.apply_patch_diff.assert_called_once()
        self.build_requests_queue_mock.ack_item.assert_called_once_with("test_item_id")


if __name__ == "__main__":
    unittest.main()
