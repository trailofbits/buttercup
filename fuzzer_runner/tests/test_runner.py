"""Tests for the fuzzer runner module."""

from unittest.mock import MagicMock, patch

from buttercup.fuzzer_runner.runner import Conf, Runner


class TestRunner:
    """Tests for the Runner class."""

    @patch("buttercup.fuzzer_runner.runner.patched_temp_dir")
    @patch("buttercup.fuzzer_runner.runner.scratch_cwd")
    @patch("os.makedirs")
    def test_run_fuzzer_initializes_engine(self, mock_makedirs, mock_scratch_cwd, mock_patched_temp_dir):
        """Test run_fuzzer"""
        from buttercup.common.types import FuzzConfiguration
        from clusterfuzz._internal.bot.fuzzers.libFuzzer import engine as libfuzzer_engine

        mock_patched_temp_dir.return_value.__enter__ = MagicMock()
        mock_patched_temp_dir.return_value.__exit__ = MagicMock(return_value=False)
        mock_scratch_cwd.return_value.__enter__ = MagicMock()
        mock_scratch_cwd.return_value.__exit__ = MagicMock(return_value=False)

        # Mock the engine methods that would fail without a real fuzzer binary
        mock_opts = MagicMock()
        mock_opts.corpus_dir = "/corpus"
        mock_opts.arguments = []
        mock_opts.strategies = []

        mock_result = MagicMock()
        mock_result.crashes = []
        mock_result.logs = "test"
        mock_result.stats = {}
        mock_result.time_executed = 1.0
        mock_result.timed_out = False

        with (
            patch.object(libfuzzer_engine.Engine, "prepare", return_value=mock_opts),
            patch.object(libfuzzer_engine.Engine, "fuzz", return_value=mock_result),
        ):
            conf = Conf(timeout=60)
            runner = Runner(conf)
            fuzzconf = FuzzConfiguration(
                corpus_dir="/corpus",
                target_path="/target",
                engine="libfuzzer",
                sanitizer="address",
            )

            result = runner.run_fuzzer(fuzzconf)

            assert result.crashes == []
            assert result.timed_out is False

    @patch("buttercup.fuzzer_runner.runner.scratch_dir")
    @patch("buttercup.fuzzer_runner.runner.patched_temp_dir")
    @patch("buttercup.fuzzer_runner.runner.scratch_cwd")
    def test_merge_corpus_initializes_engine(self, mock_scratch_cwd, mock_patched_temp_dir, mock_scratch_dir):
        """Test merge_corpus."""
        from buttercup.common.types import FuzzConfiguration
        from clusterfuzz._internal.bot.fuzzers.libFuzzer import engine as libfuzzer_engine

        mock_patched_temp_dir.return_value.__enter__ = MagicMock()
        mock_patched_temp_dir.return_value.__exit__ = MagicMock(return_value=False)
        mock_scratch_cwd.return_value.__enter__ = MagicMock()
        mock_scratch_cwd.return_value.__exit__ = MagicMock(return_value=False)

        mock_td = MagicMock()
        mock_td.path = "/tmp/scratch"
        mock_scratch_dir.return_value.__enter__ = MagicMock(return_value=mock_td)
        mock_scratch_dir.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(libfuzzer_engine.Engine, "minimize_corpus"):
            conf = Conf(timeout=60)
            runner = Runner(conf)
            fuzzconf = FuzzConfiguration(
                corpus_dir="/corpus",
                target_path="/target",
                engine="libfuzzer",
                sanitizer="address",
            )

            runner.merge_corpus(fuzzconf, "/output")
