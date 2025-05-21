import unittest
from unittest.mock import Mock, patch, MagicMock
from redis import Redis

from buttercup.fuzzing_infra.corpus_merger import MergerBot, BaseCorpus, PartitionedCorpus
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, BuildOutput
from buttercup.common.sets import FailedToAcquireLock
from buttercup.common.constants import ADDRESS_SANITIZER


class TestMergerBot(unittest.TestCase):
    def setUp(self):
        self.redis_mock = Mock(spec=Redis)
        self.runner_mock = Mock()
        self.corpus_mock = Mock()
        self.lock_mock = MagicMock()

        # Common test parameters
        self.python = "/usr/bin/python3"
        self.crs_scratch_dir = "/tmp/test_crs_scratch"
        self.timer_seconds = 10
        self.timeout_seconds = 30

        # Create the MergerBot instance with mocked runner
        with patch("buttercup.fuzzing_infra.corpus_merger.Runner") as runner_class_mock:
            runner_class_mock.return_value = self.runner_mock
            self.merger_bot = MergerBot(self.redis_mock, self.timeout_seconds, self.python, self.crs_scratch_dir)

    @patch("buttercup.fuzzing_infra.corpus_merger.Corpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.MergedCorpusSetLock")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("buttercup.fuzzing_infra.corpus_merger.BaseCorpus")
    def test_run_task_corpus_too_small(self, base_corpus_mock, scratch_dir_mock, lock_class_mock, corpus_class_mock):
        # Setup mocks
        corpus_instance = corpus_class_mock.return_value

        # Setup lock mock
        lock_instance = lock_class_mock.return_value
        lock_instance.acquire.return_value.__enter__.return_value = None

        # Setup BaseCorpus mock
        base_corpus_instance = base_corpus_mock.return_value
        partitioned_corpus_mock = MagicMock()
        # Empty local_only_files to simulate a situation where corpus is up to date
        partitioned_corpus_mock.local_only_files = set()
        base_corpus_instance.partition_corpus.return_value = partitioned_corpus_mock

        # Create test data
        task = WeightedHarness(harness_name="test_harness", package_name="test_package", task_id="task123")
        build = BuildOutput(sanitizer=ADDRESS_SANITIZER, engine="libfuzzer", task_dir="/path/to/task")
        builds = [build]

        # Call the method under test
        result = self.merger_bot.run_task(task, builds)

        # Verify behavior
        corpus_instance.hash_new_corpus.assert_called_once()
        base_corpus_mock.assert_called_once_with(
            corpus_instance, scratch_dir_mock().__enter__(), scratch_dir_mock().__enter__()
        )
        base_corpus_instance.partition_corpus.assert_called_once()

        # Should return False as there was nothing to merge
        self.assertFalse(result)

    @patch("buttercup.fuzzing_infra.corpus_merger.Corpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.MergedCorpusSetLock")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("buttercup.fuzzing_infra.corpus_merger.BaseCorpus")
    def test_run_task_failed_to_acquire_lock(
        self, base_corpus_mock, scratch_dir_mock, lock_class_mock, corpus_class_mock
    ):
        # Setup mocks
        corpus_instance = corpus_class_mock.return_value

        # Setup lock mock to fail
        lock_instance = lock_class_mock.return_value
        lock_instance.acquire.side_effect = FailedToAcquireLock()

        # Create test data
        task = WeightedHarness(harness_name="test_harness", package_name="test_package", task_id="task123")
        build = BuildOutput(sanitizer=ADDRESS_SANITIZER, engine="libfuzzer", task_dir="/path/to/task")
        builds = [build]

        # Call the method under test
        result = self.merger_bot.run_task(task, builds)

        # Verify behavior
        corpus_instance.hash_new_corpus.assert_called_once()
        lock_instance.acquire.assert_called_once()

        # BaseCorpus should not be created because lock failed
        base_corpus_mock.assert_not_called()

        # Should return False as lock acquisition failed
        self.assertFalse(result)

    @patch("buttercup.fuzzing_infra.corpus_merger.Corpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.MergedCorpusSetLock")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("buttercup.fuzzing_infra.corpus_merger.BaseCorpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("buttercup.fuzzing_infra.corpus_merger.ChallengeTask")
    def test_run_task_successful_merge(
        self,
        challenge_task_mock,
        scratch_dir_mock2,
        base_corpus_mock,
        scratch_dir_mock,
        lock_class_mock,
        corpus_class_mock,
    ):
        # Setup mocks
        corpus_instance = corpus_class_mock.return_value

        # Setup lock mock
        lock_instance = lock_class_mock.return_value
        lock_instance.acquire.return_value.__enter__.return_value = None

        # Setup BaseCorpus mock
        base_corpus_instance = base_corpus_mock.return_value
        partitioned_corpus_mock = MagicMock()
        # Non-empty local_only_files to simulate files that need merging
        partitioned_corpus_mock.local_only_files = {
            "c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "d123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }
        partitioned_corpus_mock.remote_files = {
            "a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }
        base_corpus_instance.partition_corpus.return_value = partitioned_corpus_mock

        # Setup FinalCorpus mock
        final_corpus_mock = MagicMock()
        final_corpus_mock.push_remotely.return_value = 1  # 1 file pushed
        final_corpus_mock.delete_locally.return_value = 1  # 1 file deleted
        partitioned_corpus_mock.to_final.return_value = final_corpus_mock

        # Setup scratch directory
        scratch_dir_mock.return_value.__enter__.return_value = "/tmp/scratch_dir1"
        scratch_dir_mock2.return_value.__enter__.return_value = "/tmp/scratch_dir2"

        # Setup challenge task
        task_instance = challenge_task_mock.return_value
        local_task_mock = MagicMock()
        build_dir_mock = MagicMock()
        build_dir_mock.__truediv__.return_value = "/path/to/harness"
        local_task_mock.get_build_dir.return_value = build_dir_mock
        task_instance.get_rw_copy.return_value.__enter__.return_value = local_task_mock

        # Setup test data
        task = WeightedHarness(harness_name="test_harness", package_name="test_package", task_id="task123")
        build = BuildOutput(sanitizer=ADDRESS_SANITIZER, engine="libfuzzer", task_dir="/path/to/task")
        builds = [build]

        # Call the method under test
        result = self.merger_bot.run_task(task, builds)

        # Verify behavior
        corpus_instance.hash_new_corpus.assert_called_once()
        base_corpus_mock.assert_called_once()
        base_corpus_instance.partition_corpus.assert_called_once()

        # Verify runner.merge_corpus was called
        self.runner_mock.merge_corpus.assert_called_once()

        # Verify FinalCorpus methods were called
        partitioned_corpus_mock.to_final.assert_called_once()
        final_corpus_mock.push_remotely.assert_called_once()
        final_corpus_mock.delete_locally.assert_called_once()

        # Should return True as files were merged
        self.assertTrue(result)

    def test_rehash_files(self):
        """
        This test is no longer applicable as the _rehash_files method no longer exists.
        The file hashing functionality is now handled by the Corpus.hash_corpus method.
        """
        pass  # Skipping test as functionality has been moved to Corpus class


class TestBaseCorpus(unittest.TestCase):
    @patch("buttercup.fuzzing_infra.corpus_merger.Corpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("os.path.join")
    @patch("os.path.basename")
    def test_partition_corpus(self, basename_mock, path_join_mock, scratch_dir_mock, corpus_mock):
        # Setup mocks
        corpus_instance = corpus_mock.return_value
        corpus_instance.path = "/corpus/path"
        local_dir = MagicMock()
        remote_dir = MagicMock()

        # Mock os.path.basename to extract filename
        basename_mock.side_effect = lambda path: path.split("/")[-1]

        # Mock os.path.join to return predictable paths
        def mock_path_join(*args):
            # For corpus path joins
            if args[0] == "/corpus/path":
                return f"/corpus/path/{args[1]}"
            # For local_dir joins
            elif args[0] == local_dir:
                return f"/tmp/local_dir/{args[1]}"
            # For remote_dir joins
            elif args[0] == remote_dir:
                return f"/tmp/remote_dir/{args[1]}"
            # Default
            else:
                return "/".join(args)

        path_join_mock.side_effect = mock_path_join

        # Mock local and remote corpus files
        local_files = [
            "/corpus/path/a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "/corpus/path/b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "/corpus/path/c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ]
        remote_files = [
            "/corpus/path/a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "/corpus/path/b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ]

        corpus_instance.list_local_corpus.return_value = local_files
        corpus_instance.list_remote_corpus.return_value = remote_files

        # Mock the has_hashed_name method
        with patch("buttercup.fuzzing_infra.corpus_merger.Corpus.has_hashed_name") as has_hashed_name_mock:
            has_hashed_name_mock.return_value = True

            # Create BaseCorpus instance
            base_corpus = BaseCorpus(corpus_instance, local_dir, remote_dir)

            # Test partition_corpus method
            with patch("buttercup.fuzzing_infra.corpus_merger.PartitionedCorpus") as partitioned_corpus_mock:
                partitioned_corpus_instance = MagicMock()
                partitioned_corpus_mock.return_value = partitioned_corpus_instance

                result = base_corpus.partition_corpus()

                # Verify behavior
                corpus_instance.sync_from_remote.assert_called_once()

                # Check PartitionedCorpus was created with correct parameters
                partitioned_corpus_mock.assert_called_once()
                _args, kwargs = partitioned_corpus_mock.call_args

                # Check that local_only_files and remote_files sets contain the right filenames
                self.assertEqual(
                    kwargs.get("local_only_files"), {"c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
                )
                self.assertEqual(
                    kwargs.get("remote_files"),
                    {
                        "a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                        "b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                    },
                )

                # Check result
                self.assertEqual(result, partitioned_corpus_instance)


class TestPartitionedCorpus(unittest.TestCase):
    @patch("buttercup.fuzzing_infra.corpus_merger.Corpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("shutil.copy")
    @patch("os.path.join")
    @patch("os.path.exists")
    def test_initialization(self, path_exists_mock, path_join_mock, shutil_copy_mock, scratch_dir_mock, corpus_mock):
        # Setup mocks
        corpus_instance = corpus_mock.return_value
        corpus_instance.path = "/corpus/path"
        local_dir = MagicMock()
        remote_dir = MagicMock()

        # Mock os.path.exists to always return True
        path_exists_mock.return_value = True

        # Mock os.path.join to return predictable paths
        def mock_path_join(*args):
            # For corpus path joins
            if args[0] == "/corpus/path":
                return f"/corpus/path/{args[1]}"
            # For local_dir joins
            elif args[0] == local_dir:
                return f"/tmp/local_dir/{args[1]}"
            # For remote_dir joins
            elif args[0] == remote_dir:
                return f"/tmp/remote_dir/{args[1]}"
            # Default
            else:
                return "/".join(args)

        path_join_mock.side_effect = mock_path_join

        # Create test data
        local_only_files = {"c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
        remote_files = {
            "a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }

        # Create PartitionedCorpus instance

        partitioned_corpus = PartitionedCorpus(
            corpus=corpus_instance,
            local_dir=local_dir,
            remote_dir=remote_dir,
            local_only_files=local_only_files,
            remote_files=remote_files,
        )

        # Verify attributes were set correctly
        self.assertEqual(partitioned_corpus.corpus, corpus_instance)
        self.assertEqual(partitioned_corpus.local_dir, local_dir)
        self.assertEqual(partitioned_corpus.remote_dir, remote_dir)
        self.assertEqual(partitioned_corpus.local_only_files, local_only_files)
        self.assertEqual(partitioned_corpus.remote_files, remote_files)

        # Verify files were copied to the correct directories
        calls = [
            # Local only files
            unittest.mock.call(
                "/corpus/path/c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "/tmp/local_dir/c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            ),
            # Remote files
            unittest.mock.call(
                "/corpus/path/a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "/tmp/remote_dir/a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            ),
            unittest.mock.call(
                "/corpus/path/b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "/tmp/remote_dir/b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            ),
        ]
        shutil_copy_mock.assert_has_calls(calls, any_order=True)
        self.assertEqual(shutil_copy_mock.call_count, 3)

    @patch("buttercup.fuzzing_infra.corpus_merger.Corpus")
    @patch("buttercup.fuzzing_infra.corpus_merger.node_local.scratch_dir")
    @patch("os.path.join")
    @patch("os.listdir")
    @patch("shutil.copy")
    @patch("buttercup.fuzzing_infra.corpus_merger.PartitionedCorpus.__init__")
    @patch("buttercup.fuzzing_infra.corpus_merger.FinalCorpus")
    def test_to_final(
        self,
        final_corpus_mock,
        partitioned_init_mock,
        shutil_copy_mock,
        listdir_mock,
        path_join_mock,
        scratch_dir_mock,
        corpus_mock,
    ):
        # Setup mocks
        corpus_instance = corpus_mock.return_value
        corpus_instance.path = "/corpus/path"
        local_dir = MagicMock()
        remote_dir = MagicMock()

        # Mock FinalCorpus to return a known instance
        final_corpus_instance = MagicMock()
        final_corpus_mock.return_value = final_corpus_instance

        # Override PartitionedCorpus.__init__ to avoid file operations
        partitioned_init_mock.return_value = None

        # Mock os.path.join to return predictable paths
        def mock_path_join(*args):
            # For corpus path joins
            if args[0] == "/corpus/path":
                return f"/corpus/path/{args[1]}"
            # For local_dir joins
            elif args[0] == local_dir:
                return f"/tmp/local_dir/{args[1]}"
            # For remote_dir joins
            elif args[0] == remote_dir:
                return f"/tmp/remote_dir/{args[1]}"
            # Default
            else:
                return "/".join(args)

        path_join_mock.side_effect = mock_path_join

        # Setup test data
        local_only_files = {
            "c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "d123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }
        remote_files = {
            "a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }

        # Mock os.listdir to return files in remote dir after merge
        # This simulates file c having coverage benefit and being preserved
        # while file d does not add coverage and should be deleted
        listdir_mock.return_value = [
            "a123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ]

        # Create BaseCorpus instance
        from buttercup.fuzzing_infra.corpus_merger import BaseCorpus

        _base_corpus = BaseCorpus(corpus_instance, local_dir, remote_dir)

        # Create PartitionedCorpus instance and manually set its attributes

        partitioned_corpus = PartitionedCorpus.__new__(PartitionedCorpus)
        partitioned_corpus.corpus = corpus_instance
        partitioned_corpus.local_dir = local_dir
        partitioned_corpus.remote_dir = remote_dir
        partitioned_corpus.local_only_files = local_only_files
        partitioned_corpus.remote_files = remote_files

        # Test to_final method
        final_corpus = partitioned_corpus.to_final()

        # Verify corpus was hashed
        corpus_instance.hash_corpus.assert_called_once_with(remote_dir)

        # Verify FinalCorpus was created with the right parameters
        expected_push_remotely = {"c123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
        expected_delete_locally = {"d123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
        final_corpus_mock.assert_called_once_with(corpus_instance, expected_push_remotely, expected_delete_locally)

        # Check if the method returns the expected FinalCorpus instance
        self.assertEqual(final_corpus, final_corpus_instance)


class TestFinalCorpus(unittest.TestCase):
    @patch("buttercup.common.corpus.Corpus")
    def test_push_remotely(self, corpus_mock):
        """Test that push_remotely method works as expected."""
        # Import FinalCorpus
        from buttercup.fuzzing_infra.corpus_merger import FinalCorpus

        # Create corpus mock
        corpus_instance = corpus_mock.return_value
        corpus_instance.path = "/corpus/path"

        # Test data
        push_remotely = {"file1", "file2"}
        delete_locally = {"file3", "file4"}

        # Create FinalCorpus instance
        final_corpus = FinalCorpus(corpus_instance, push_remotely, delete_locally)

        # Call push_remotely method
        result = final_corpus.push_remotely()

        # Test that corpus.sync_specific_files_to_remote was called with the right files
        corpus_instance.sync_specific_files_to_remote.assert_called_once_with(push_remotely)

        # Verify result
        self.assertEqual(result, 2)  # Should return the number of files pushed

        # Verify that the set was cleared
        self.assertEqual(len(push_remotely), 0)

    @patch("buttercup.common.corpus.Corpus")
    def test_delete_locally(self, corpus_mock):
        """Test that delete_locally method works as expected."""
        # Import FinalCorpus
        from buttercup.fuzzing_infra.corpus_merger import FinalCorpus

        # Create corpus mock
        corpus_instance = corpus_mock.return_value
        corpus_instance.path = "/corpus/path"

        # Test data
        push_remotely = {"file1", "file2"}
        delete_locally = {"file3", "file4"}

        # Create FinalCorpus instance
        final_corpus = FinalCorpus(corpus_instance, push_remotely, delete_locally)

        # Call delete_locally method
        result = final_corpus.delete_locally()

        # Test that corpus.remove_local_file was called for each file
        calls = [unittest.mock.call("file3"), unittest.mock.call("file4")]
        corpus_instance.remove_local_file.assert_has_calls(calls, any_order=True)

        # Verify result
        self.assertEqual(result, 2)  # Should return the number of files deleted

        # Verify that the set was cleared
        self.assertEqual(len(delete_locally), 0)

    @patch("buttercup.common.corpus.Corpus")
    def test_delete_locally_error_handling(self, corpus_mock):
        """Test that delete_locally method handles errors gracefully."""
        # Import FinalCorpus
        from buttercup.fuzzing_infra.corpus_merger import FinalCorpus

        # Create corpus mock
        corpus_instance = corpus_mock.return_value
        corpus_instance.path = "/corpus/path"

        # Make remove_local_file raise an exception for one file
        def side_effect(file):
            if file == "file3":
                raise Exception("Test exception")

        corpus_instance.remove_local_file.side_effect = side_effect

        # Test data
        push_remotely = {"file1", "file2"}
        delete_locally = {"file3", "file4"}

        # Create FinalCorpus instance
        final_corpus = FinalCorpus(corpus_instance, push_remotely, delete_locally)

        # Call delete_locally method
        result = final_corpus.delete_locally()

        # Test that corpus.remove_local_file was called for each file
        calls = [unittest.mock.call("file3"), unittest.mock.call("file4")]
        corpus_instance.remove_local_file.assert_has_calls(calls, any_order=True)

        # Verify result
        self.assertEqual(result, 1)  # Only one file was successfully deleted

        # Verify that the set was cleared
        self.assertEqual(len(delete_locally), 0)


if __name__ == "__main__":
    unittest.main()
