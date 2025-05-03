from buttercup.common.datastructures.msg_pb2 import TracedCrash
from buttercup.common.clusterfuzz_parser.slice import StackFrame
from buttercup.common import stack_parsing
from buttercup.orchestrator.task_server.models.types import SARIFBroadcastDetail
from typing import List, Tuple
from pathlib import Path
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class SarifInfo:
    file: Path
    lines: Tuple[int, int]
    function: str | None
    cwe: str | None


@dataclass
class Frame:
    file: Path
    line: int
    function: str | None


@dataclass
class SarifMatch:
    sarif_info: SarifInfo
    frame: Frame
    matches_function: bool = False
    matches_stripped_function: bool = False
    matches_filename: bool = False
    matches_full_path: bool = False
    matches_lines: bool = False


def match(sarif_broadcast: SARIFBroadcastDetail, traced_crash: TracedCrash) -> SarifMatch | None:
    """
    Match a SARIF broadcast with a traced crash.

    Args:
        sarif_broadcast: The SARIF broadcast to match
        traced_crash: The traced crash to match against

    Returns:
        A SarifMatch object if a match is found between the SARIF and traced crash, None otherwise
    """

    # Extract SARIF details
    sarif_infos = _sarif_detail(sarif_broadcast)

    if not sarif_infos:
        return None

    # Parse the stacktrace
    stacktrace = stack_parsing.parse_stacktrace(traced_crash.tracer_stacktrace)

    # Check each thread for a match
    for thread_frame in stacktrace.frames:
        match = _match_thread_callstack(thread_frame, sarif_infos)
        if match:
            return match

    return None


def _sarif_detail(sarif_broadcast: SARIFBroadcastDetail) -> List[SarifInfo]:
    """
    Extract detailed information from a SARIF broadcast.

    Args:
        sarif_broadcast: The SARIF broadcast to extract details from

    Returns:
        List of SarifInfo objects containing file, line, function, and CWE information
    """
    sarif_infos = []

    # Process each run in the SARIF
    for run in sarif_broadcast.sarif.get("runs", []):
        # Get the artifacts (files) mentioned in the SARIF
        artifacts = run.get("artifacts", [])

        # Process each result (finding)
        for result in run.get("results", []):
            # Extract the CWE information from the rule ID or message
            rule_id = result.get("ruleId", "")
            cwe = None
            if "CWE-" in rule_id:
                cwe = rule_id
            elif result.get("message", {}).get("text", "") and "CWE-" in result.get("message", {}).get("text", ""):
                # Extract CWE from message text
                message_text = result.get("message", {}).get("text", "")
                cwe_matches = [part for part in message_text.split() if part.startswith("CWE-")]
                if cwe_matches:
                    cwe = cwe_matches[0]

            # Process each location in the result
            for location in result.get("locations", []):
                physical_location = location.get("physicalLocation", {})

                # Get the artifact index from the location
                artifact_location = physical_location.get("artifactLocation", {})
                artifact_index = artifact_location.get("index", 0)

                # Get the file URI directly from the location or from the referenced artifact
                file_uri = artifact_location.get("uri")
                if file_uri is None and 0 <= artifact_index < len(artifacts):
                    file_uri = artifacts[artifact_index].get("location", {}).get("uri")

                if not file_uri:
                    continue

                # Get line information
                region = physical_location.get("region", {})
                start_line = region.get("startLine")
                end_line = region.get("endLine")
                if start_line is None or end_line is None:
                    continue

                # Extract function name if available
                function_name = None
                # Try to get function name from logical locations if available
                if "logicalLocations" in location:
                    for logical_location in location.get("logicalLocations", []):
                        if "name" in logical_location:
                            function_name = logical_location.get("name")
                            break

                # Create SarifInfo object and add to the list
                sarif_info = SarifInfo(
                    file=Path(file_uri), lines=(start_line, end_line), function=function_name, cwe=cwe
                )
                sarif_infos.append(sarif_info)

    return sarif_infos


def _match_thread_callstack(frames: List[StackFrame], sarif_infos: List[SarifInfo]) -> SarifMatch | None:
    """
    Match a thread frame with SARIF information.

    Args:
        frames: List of stack frames from a thread
        sarif_infos: List of SARIF information objects

    Returns:
        True if any frame matches any SARIF info, False otherwise
    """
    if not frames:
        return None

    if not sarif_infos:
        return None

    for frame in frames:
        try:
            frame = _get_frame(frame)
            if frame is None:
                continue
            match = _match_frame(frame, sarif_infos)
            if match:
                return match
        except Exception as e:
            logger.error(f"Error getting frame {frame}: {e}")
            continue

    return None


def _get_frame(frame: StackFrame) -> Frame | None:
    """
    Get a Frame object from a StackFrame object.
    NOTE: We require the filename to be present in the StackFrame object.
    """
    if frame.filename is None:
        return None

    return Frame(file=Path(frame.filename), line=int(frame.fileline), function=frame.function_name)


def _match_frame(frame: Frame, sarif_infos: List[SarifInfo]) -> SarifMatch | None:
    """
    Match a frame with SARIF information.

    Tries to match based on:
    1. File path and line number
    2. File name (without path) and line number
    3. Function name if available

    Args:
        frame: Stack frame from the crash
        sarif_infos: List of SARIF information objects

    Returns:
        True if a match is found, False otherwise
    """

    def line_match(frame_line: int | str, info_lines: Tuple[int, int]) -> bool:
        if isinstance(frame_line, str):
            frame_line = int(frame_line)
        return frame_line >= info_lines[0] and frame_line <= info_lines[1]

    def stripped_function_match(frame_function: str, info_function: str) -> bool:
        """
        Match a function name by stripping the OSS_FUZZ_ prefix.
        """
        if frame_function.startswith("OSS_FUZZ_"):
            frame_function = frame_function.split("OSS_FUZZ_")[1]
            return frame_function == info_function
        return False

    for info in sarif_infos:
        try:
            matches_lines = line_match(frame.line, info.lines)
            matches_function = frame.function == info.function
            matches_filename = frame.file.name == info.file.name
            matches_full_path = frame.file == info.file
            stripped_matches_function = stripped_function_match(frame.function, info.function)

            # Either match lines and filename (or full path) or function name
            location_match = matches_lines and (matches_filename or matches_full_path)
            if location_match or matches_function or stripped_matches_function:
                return SarifMatch(
                    sarif_info=info,
                    frame=frame,
                    matches_function=matches_function,
                    matches_stripped_function=stripped_matches_function,
                    matches_filename=matches_filename,
                    matches_full_path=matches_full_path,
                    matches_lines=matches_lines,
                )
        except Exception as e:
            logger.error(f"Error matching frame {frame} with SARIF info {info}: {e}")
            continue

    return None
