#!/usr/bin/env python3
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from redis import Redis
from buttercup.common.maps import CoverageMap, FunctionCoverage, HarnessWeights

# Add matplotlib import for visualization
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


# Move _print_coverage_metrics to be a free function
def print_coverage_metrics(func_coverage_list: List[FunctionCoverage], snapshot_count: int) -> None:
    """
    Print coverage metrics for the given list of function coverage objects.

    Args:
        func_coverage_list: List of FunctionCoverage objects
        snapshot_count: The current snapshot count
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_functions = len(func_coverage_list)

    if total_functions == 0:
        print(f"\nSnapshot {snapshot_count} ({timestamp}): No function coverage data")
        return

    total_lines = sum(fc.total_lines for fc in func_coverage_list)
    covered_lines = sum(fc.covered_lines for fc in func_coverage_list)
    coverage_percentage = (covered_lines / total_lines * 100) if total_lines > 0 else 0

    print("\n" + "=" * 80)
    print(f"Snapshot {snapshot_count} ({timestamp}):")
    print(f"  Functions: {total_functions}")
    print(f"  Total lines: {total_lines}")
    print(f"  Covered lines: {covered_lines}")
    print(f"  Coverage: {coverage_percentage:.2f}%")
    print("-" * 80)


def coverage_data_equal(old_data: List[Dict], new_data: List[Dict]) -> bool:
    """
    Compare two coverage data lists to check if they are equal.

    Args:
        old_data: Previous coverage data
        new_data: Current coverage data

    Returns:
        True if coverage data is the same, False otherwise
    """
    if len(old_data) != len(new_data):
        return False

    # Sort both lists by function_name to ensure consistent comparison
    old_sorted = sorted(old_data, key=lambda x: x["function_name"])
    new_sorted = sorted(new_data, key=lambda x: x["function_name"])

    for old_item, new_item in zip(old_sorted, new_sorted):
        if (
            old_item["function_name"] != new_item["function_name"]
            or old_item["total_lines"] != new_item["total_lines"]
            or old_item["covered_lines"] != new_item["covered_lines"]
            or set(old_item["function_paths"]) != set(new_item["function_paths"])
        ):
            return False

    return True


class CoverageMonitor:
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        task_id: str = None,
        output_dir: str = "coverage_data",
        interval: int = 10,
    ):
        self.redis = Redis(host=redis_host, port=redis_port)
        self.task_id = task_id
        self.output_dir = Path(output_dir)
        self.interval = interval

        os.makedirs(self.output_dir, exist_ok=True)

    def _serialize_function_coverage(self, fc: FunctionCoverage) -> Dict[str, Any]:
        """Convert FunctionCoverage object to a serializable dictionary."""
        return {
            "function_name": fc.function_name,
            "function_paths": list(fc.function_paths),
            "total_lines": fc.total_lines,
            "covered_lines": fc.covered_lines,
            "coverage_percentage": (fc.covered_lines / fc.total_lines * 100) if fc.total_lines > 0 else 0,
        }

    def monitor_coverage(self, duration_seconds: int = None) -> str:
        """
        Monitor function coverage over time and save results to a file for all packages and harnesses.

        Args:
            duration_seconds: How long to run the monitor. If None, run indefinitely.

        Returns:
            Path to the output file.
        """
        coverage_snapshots = []
        start_time = time.time()
        filename = f"coverage_all_harnesses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = self.output_dir / filename
        last_coverage_data = {}  # Track last coverage data by package/harness

        try:
            print("Starting coverage monitoring for all packages and harnesses")
            print(f"Output will be saved to {output_path}")

            # Wait until at least one harness is available
            harness_weights = HarnessWeights(self.redis)
            print("Waiting for harnesses to appear...")
            harnesses_found = False
            last_print_time = time.time()
            wait_iteration = 0

            while not harnesses_found:
                all_harnesses = harness_weights.list_harnesses()

                # If task_id is specified, filter harnesses by matching task_id
                matching_harnesses = all_harnesses
                if self.task_id:
                    matching_harnesses = [h for h in all_harnesses if h.task_id == self.task_id]

                if matching_harnesses:
                    harnesses_found = True
                    if self.task_id:
                        print(f"Found {len(matching_harnesses)} harnesses for task_id: {self.task_id}!")
                    else:
                        print(f"Found {len(all_harnesses)} harnesses!")
                    break

                current_time = time.time()
                # Only print the waiting message every 15 seconds
                if current_time - last_print_time >= 15:
                    wait_seconds = wait_iteration * 1.0
                    if self.task_id:
                        print(f"No harnesses found for task_id {self.task_id} yet. Waiting... ({wait_seconds:.1f}s)")
                    else:
                        print(f"No harnesses found yet. Waiting... ({wait_seconds:.1f}s)")
                    last_print_time = current_time
                time.sleep(1.0)
                wait_iteration += 1

            print(f"Collecting data every {self.interval} seconds...")
            snapshot_count = 0

            while True:
                # Check if we've exceeded the duration
                if duration_seconds and time.time() - start_time > duration_seconds:
                    break

                # Get all available harnesses
                all_harnesses = harness_weights.list_harnesses()

                # Filter harnesses by task_id if specified
                matching_harnesses = all_harnesses
                if self.task_id:
                    matching_harnesses = [h for h in all_harnesses if h.task_id == self.task_id]

                print(f"\nFound {len(matching_harnesses)} harnesses for monitoring")

                # Create a snapshot with the coverage data for all harnesses
                snapshot_count += 1
                timestamp = time.time()
                snapshot = {"timestamp": timestamp, "harnesses": {}}

                # Collect coverage data for each harness
                for harness in matching_harnesses:
                    harness_key = f"{harness.package_name}-{harness.harness_name}"

                    print(f"Collecting coverage for {harness_key}")

                    # Get coverage data for this harness
                    coverage_map = CoverageMap(self.redis, harness.harness_name, harness.package_name, harness.task_id)
                    func_coverage_list = coverage_map.list_function_coverage()

                    # Create serialized coverage data
                    current_coverage_data = [self._serialize_function_coverage(fc) for fc in func_coverage_list]

                    # Check if coverage data has changed
                    is_same_as_last = False
                    if harness_key in last_coverage_data:
                        is_same_as_last = coverage_data_equal(last_coverage_data[harness_key], current_coverage_data)

                    # Prepare harness-specific data
                    harness_data = {
                        "package_name": harness.package_name,
                        "harness_name": harness.harness_name,
                        "task_id": harness.task_id,
                        # If coverage hasn't changed, store an empty list to save space
                        "coverage_data": [] if is_same_as_last else current_coverage_data,
                        "same_as_previous": is_same_as_last,
                    }

                    # Print coverage metrics for this harness
                    print(f"\n--- {harness_key} ---")
                    print_coverage_metrics(func_coverage_list, snapshot_count)

                    # Add to the snapshot
                    snapshot["harnesses"][harness_key] = harness_data

                    # Update last coverage data
                    if not is_same_as_last:
                        last_coverage_data[harness_key] = current_coverage_data

                # Add the snapshot
                coverage_snapshots.append(snapshot)

                # Save the current state to disk
                temp_path = output_path.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(coverage_snapshots, f, indent=2)
                os.rename(temp_path, output_path)

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")

        print(f"Coverage data saved to {output_path}")
        return str(output_path)

    @staticmethod
    def _extract_metrics(
        coverage_snapshots: List[Dict],
    ) -> Tuple[List[datetime], List[int], List[int], List[int], List[float]]:
        """
        Extract metrics from coverage snapshots for analysis and visualization.

        Returns:
            Tuple containing:
            - timestamps: List of datetime objects
            - function_counts: List of function counts for each snapshot
            - total_lines: List of total line counts for each snapshot
            - covered_lines: List of covered line counts for each snapshot
            - coverage_percentages: List of coverage percentages for each snapshot
        """
        timestamps = []
        function_counts = []
        total_lines_list = []
        covered_lines_list = []
        coverage_percentages = []

        for snapshot in coverage_snapshots:
            timestamp = datetime.fromtimestamp(snapshot["timestamp"])
            coverage_data = snapshot.get("coverage_data", [])

            total_functions = len(coverage_data)
            total_lines = sum(item["total_lines"] for item in coverage_data) if coverage_data else 0
            covered_lines = sum(item["covered_lines"] for item in coverage_data) if coverage_data else 0
            coverage_percentage = (covered_lines / total_lines * 100) if total_lines > 0 else 0

            timestamps.append(timestamp)
            function_counts.append(total_functions)
            total_lines_list.append(total_lines)
            covered_lines_list.append(covered_lines)
            coverage_percentages.append(coverage_percentage)

        return timestamps, function_counts, total_lines_list, covered_lines_list, coverage_percentages

    @staticmethod
    def _create_visualization(
        file_path: str,
        timestamps: List[datetime],
        function_counts: List[int],
        total_lines: List[int],
        covered_lines: List[int],
        coverage_percentages: List[float],
    ) -> Optional[str]:
        """
        Create a visualization of coverage metrics over time.

        Returns:
            Path to the generated image file, or None if visualization failed.
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib is not available. Install with 'pip install matplotlib' to enable visualization.")
            return None

        if not timestamps:
            print("No data available for visualization.")
            return None

        # Create the output filename based on the input file
        output_path = Path(file_path + ".png")

        # Create a figure with two y-axes
        fig, ax1 = plt.subplots(figsize=(12, 8))
        ax2 = ax1.twinx()

        # Plot data on the primary y-axis (lines)
        line1 = ax1.plot(timestamps, total_lines, "b-", label="Total Lines")
        line2 = ax1.plot(timestamps, covered_lines, "g-", label="Covered Lines")

        # Plot data on the secondary y-axis (functions)
        line3 = ax2.plot(timestamps, function_counts, "r-", label="Functions")

        # Add coverage percentage as a filled area
        ax3 = ax1.twinx()
        ax3.spines["right"].set_position(("axes", 1.1))  # Offset the right spine
        _line4 = ax3.fill_between(timestamps, coverage_percentages, alpha=0.2, color="orange")
        line4_line = ax3.plot(timestamps, coverage_percentages, "orange", label="Coverage %")

        # Set labels and title
        ax1.set_xlabel("Time")
        ax1.set_ylabel("Line Count", color="b")
        ax2.set_ylabel("Function Count", color="r")
        ax3.set_ylabel("Coverage %", color="orange")

        # Set y-axis limits
        ax1.set_ylim(bottom=0)
        ax2.set_ylim(bottom=0)
        ax3.set_ylim(bottom=0, top=100)

        # Configure x-axis for better time display
        plt.gcf().autofmt_xdate()
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))

        # Add a grid
        ax1.grid(True, linestyle="--", alpha=0.7)

        # Combine all lines for the legend
        lines = line1 + line2 + line3 + line4_line
        labels = [line.get_label() for line in lines]
        ax1.legend(lines, labels, loc="upper left")

        # Add title
        plt.title("Code Coverage Metrics Over Time")

        # Adjust layout and save
        plt.tight_layout()
        plt.savefig(output_path)
        print(f"Visualization saved to {output_path}")

        return str(output_path)

    @staticmethod
    def analyze_coverage_file(
        file_path: str, harness_key: str = None, visualize: bool = False, list_only: bool = False
    ) -> None:
        """
        Analyze a previously recorded coverage file and print summary statistics.

        Args:
            file_path: Path to the coverage data file.
            harness_key: Optional harness key in the format "package_name-harness_name" to analyze.
                         If None, analyze all harnesses in the file.
            visualize: Whether to generate a visualization of the data.
            list_only: If True, only list the available harnesses without analyzing.
        """
        try:
            with open(file_path, "r") as f:
                coverage_snapshots = json.load(f)

            if not coverage_snapshots:
                print("No coverage data found in the file.")
                return

            # Extract all unique harness keys across all snapshots
            all_harness_keys = set()
            for snapshot in coverage_snapshots:
                all_harness_keys.update(snapshot["harnesses"].keys())

            # List all available harnesses
            print(f"Coverage file: {file_path}")
            print(
                f"Time range: {datetime.fromtimestamp(coverage_snapshots[0]['timestamp']).strftime('%Y-%m-%d %H:%M:%S')} - "
                f"{datetime.fromtimestamp(coverage_snapshots[-1]['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            print(f"Total snapshots: {len(coverage_snapshots)}")
            print("\nAvailable harnesses:")

            for idx, key in enumerate(sorted(all_harness_keys)):
                print(f"  {idx + 1}. {key}")

            # If list_only, stop here
            if list_only:
                print("\nUse --harness-key option to analyze a specific harness.")
                return

            # If no harness specified and we have multiple, ask user to specify
            if harness_key is None and len(all_harness_keys) > 1:
                print("\nMultiple harnesses found. Please specify one using --harness-key option.")
                return

            # If harness specified but not found, show error
            if harness_key and harness_key not in all_harness_keys:
                print(f"Error: Harness '{harness_key}' not found in the coverage file.")
                print("Available harnesses:", ", ".join(sorted(all_harness_keys)))
                return

            # If we have only one harness and none specified, use that one
            if harness_key is None and len(all_harness_keys) == 1:
                harness_key = next(iter(all_harness_keys))
                print(f"\nUsing the only available harness: {harness_key}")

            print(f"\nAnalyzing coverage for harness: {harness_key}")
            print("=" * 80)

            # Reconstruct the full coverage data for each snapshot
            last_full_coverage_data = None

            for i, snapshot in enumerate(coverage_snapshots):
                timestamp = datetime.fromtimestamp(snapshot["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")

                if harness_key not in snapshot["harnesses"]:
                    print(f"Snapshot {i + 1} ({timestamp}): Harness not present")
                    continue

                harness_data = snapshot["harnesses"][harness_key]
                same_as_previous = harness_data.get("same_as_previous", False)
                coverage_data = harness_data["coverage_data"]

                # Handle empty or same-as-previous data
                if same_as_previous and last_full_coverage_data is not None:
                    coverage_data = last_full_coverage_data
                    print(f"Snapshot {i + 1} ({timestamp}): No change from previous snapshot")
                elif not coverage_data:  # Empty list also indicates same as previous
                    if last_full_coverage_data is not None:
                        coverage_data = last_full_coverage_data
                        print(f"Snapshot {i + 1} ({timestamp}): No change from previous snapshot")
                    else:
                        print(f"Snapshot {i + 1} ({timestamp}): No function coverage data")
                        continue
                else:
                    # Store this as the last full coverage data
                    last_full_coverage_data = coverage_data

                # Convert the serialized coverage data back to FunctionCoverage objects
                func_coverage_list = []
                for item in coverage_data:
                    fc = FunctionCoverage()
                    fc.function_name = item["function_name"]
                    for path in item["function_paths"]:
                        fc.function_paths.append(path)
                    fc.total_lines = item["total_lines"]
                    fc.covered_lines = item["covered_lines"]
                    func_coverage_list.append(fc)

                # Use the free function to print metrics
                print_coverage_metrics(func_coverage_list, i + 1)

            # Generate visualization if requested
            if visualize:
                if MATPLOTLIB_AVAILABLE:
                    # Create expanded snapshots for visualization, with full coverage data
                    expanded_snapshots = []
                    last_full_coverage_data = None

                    for snapshot in coverage_snapshots:
                        # Skip snapshots where this harness isn't present
                        if harness_key not in snapshot["harnesses"]:
                            continue

                        harness_data = snapshot["harnesses"][harness_key]
                        same_as_previous = harness_data.get("same_as_previous", False)
                        coverage_data = harness_data["coverage_data"]

                        # Create a simplified snapshot format for _extract_metrics
                        expanded_snapshot = {"timestamp": snapshot["timestamp"]}

                        # Fill in coverage data appropriately
                        if (same_as_previous or not coverage_data) and last_full_coverage_data is not None:
                            expanded_snapshot["coverage_data"] = last_full_coverage_data
                        elif not same_as_previous and coverage_data:
                            last_full_coverage_data = coverage_data
                            expanded_snapshot["coverage_data"] = coverage_data
                        else:
                            # Skip snapshots with no coverage data
                            continue

                        expanded_snapshots.append(expanded_snapshot)

                    if expanded_snapshots:
                        timestamps, function_counts, total_lines, covered_lines, coverage_percentages = (
                            CoverageMonitor._extract_metrics(expanded_snapshots)
                        )
                        CoverageMonitor._create_visualization(
                            f"{file_path}_{harness_key}",
                            timestamps,
                            function_counts,
                            total_lines,
                            covered_lines,
                            coverage_percentages,
                        )
                    else:
                        print("\nNo data available for visualization.")
                else:
                    print("\nVisualization requested but matplotlib is not available.")
                    print("Install matplotlib with: pip install matplotlib")

        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Error analyzing coverage file: {e}")


def main():
    parser = argparse.ArgumentParser(description="Monitor function coverage over time")

    # Add common arguments
    parser.add_argument("--redis-host", default="localhost", help="Redis server host")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis server port")
    parser.add_argument("--output-dir", default="coverage_data", help="Directory to save coverage data")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor function coverage over time")
    monitor_parser.add_argument("--task-id", help="Task ID to filter harnesses (optional)")
    monitor_parser.add_argument("--interval", type=int, default=10, help="Interval between snapshots in seconds")
    monitor_parser.add_argument(
        "--duration", type=int, help="Duration to run the monitor in seconds (default: run indefinitely)"
    )

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a previously recorded coverage file")
    analyze_parser.add_argument("file_path", help="Path to the coverage data file")
    analyze_parser.add_argument("--harness-key", help="Harness key to analyze in format 'package_name-harness_name'")
    analyze_parser.add_argument(
        "--visualize", "-v", action="store_true", help="Generate visualization of coverage metrics"
    )
    analyze_parser.add_argument("--list", "-l", action="store_true", help="List available harnesses in the file")

    args = parser.parse_args()

    if args.command == "monitor":
        monitor = CoverageMonitor(
            redis_host=args.redis_host,
            redis_port=args.redis_port,
            task_id=args.task_id,
            output_dir=args.output_dir,
            interval=args.interval,
        )
        monitor.monitor_coverage(args.duration)

    elif args.command == "analyze":
        CoverageMonitor.analyze_coverage_file(
            args.file_path, harness_key=args.harness_key, visualize=args.visualize, list_only=args.list
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
