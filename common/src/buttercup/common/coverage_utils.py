"""Utilities for working with coverage data and uncovered line tracking."""

from dataclasses import dataclass

from buttercup.common.datastructures.msg_pb2 import UncoveredLines


@dataclass
class LineRange:
    """A range of consecutive lines."""

    start: int
    length: int

    @property
    def end(self) -> int:
        """Return the end line (inclusive)."""
        return self.start + self.length - 1


@dataclass
class UncoveredRanges:
    """Represents uncovered line ranges in a function.

    This class converts between line sets and the protobuf UncoveredLines format,
    which uses run-length encoding (starts + lengths) for compact storage.
    """

    ranges: list[LineRange]
    function_start_line: int
    function_end_line: int

    @classmethod
    def from_line_sets(
        cls,
        total_lines: set[int],
        covered_lines: set[int],
        function_start_line: int,
        function_end_line: int,
    ) -> "UncoveredRanges | None":
        """Create UncoveredRanges from total and covered line sets.

        Args:
            total_lines: Set of all lines in the function
            covered_lines: Set of lines that were executed
            function_start_line: First line of the function
            function_end_line: Last line of the function

        Returns:
            UncoveredRanges if there are uncovered lines, None otherwise
        """
        uncovered = total_lines - covered_lines
        if not uncovered:
            return None

        # Convert to sorted list and group into consecutive ranges
        sorted_lines = sorted(uncovered)
        ranges: list[LineRange] = []
        range_start = sorted_lines[0]
        range_length = 1

        for i in range(1, len(sorted_lines)):
            if sorted_lines[i] == sorted_lines[i - 1] + 1:
                # Consecutive line, extend current range
                range_length += 1
            else:
                # Gap found, save current range and start new one
                ranges.append(LineRange(range_start, range_length))
                range_start = sorted_lines[i]
                range_length = 1

        # Don't forget the last range
        ranges.append(LineRange(range_start, range_length))

        return cls(
            ranges=ranges,
            function_start_line=function_start_line,
            function_end_line=function_end_line,
        )

    @classmethod
    def from_protobuf(cls, proto: UncoveredLines) -> "UncoveredRanges":
        """Create UncoveredRanges from a protobuf UncoveredLines message.

        Args:
            proto: The protobuf UncoveredLines message

        Returns:
            UncoveredRanges instance
        """
        ranges = [
            LineRange(start=start, length=length) for start, length in zip(proto.starts, proto.lengths, strict=True)
        ]
        return cls(
            ranges=ranges,
            function_start_line=proto.function_start_line,
            function_end_line=proto.function_end_line,
        )

    def to_protobuf(self) -> UncoveredLines:
        """Convert to a protobuf UncoveredLines message.

        Returns:
            UncoveredLines protobuf message
        """
        proto = UncoveredLines()
        proto.starts.extend(r.start for r in self.ranges)
        proto.lengths.extend(r.length for r in self.ranges)
        proto.function_start_line = self.function_start_line
        proto.function_end_line = self.function_end_line
        return proto

    def get_uncovered_lines(self) -> set[int]:
        """Get all uncovered lines as a set.

        Returns:
            Set of uncovered line numbers
        """
        lines: set[int] = set()
        for r in self.ranges:
            lines.update(range(r.start, r.start + r.length))
        return lines

    def total_uncovered_count(self) -> int:
        """Get total count of uncovered lines.

        Returns:
            Number of uncovered lines
        """
        return sum(r.length for r in self.ranges)
