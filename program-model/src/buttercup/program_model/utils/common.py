import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass
class FunctionBody:
    """Class to store function body information."""

    body: str
    """Body of the function."""

    start_line: int
    """Start line of the function in the file (1-based)."""

    end_line: int
    """End line of the function in the file (1-based)."""

    def __eq__(self, other):
        """Two function bodies are equal if they have the same body and start and end lines."""
        if not isinstance(other, FunctionBody):
            return NotImplemented
        return (
            self.body == other.body
            and self.start_line == other.start_line
            and self.end_line == other.end_line
        )

    def __hash__(self):
        """Hash based on body and start and end lines."""
        return hash((self.body, self.start_line, self.end_line))


@dataclass
class Function:
    """Class to store function information. This class collects all the bodies
    of a function in a single file. There might be multiple bodies for a single
    function if the function is defined in multiple places in the file (e.g.
    under #ifdef or overloaded methods)."""

    name: str
    """Name of the function."""

    file_path: Path
    """Path to the file containing the function."""

    bodies: list[FunctionBody] = field(default_factory=list)
    """List of function bodies."""

    def __eq__(self, other):
        """Two functions are equal if they have the same name and file path."""
        if not isinstance(other, Function):
            return NotImplemented
        return (
            self.name == other.name
            and self.file_path == other.file_path
            and frozenset(self.bodies) == frozenset(other.bodies)
        )

    def __hash__(self):
        """Hash based on name and file path."""
        return hash((self.name, self.file_path, frozenset(self.bodies)))

    def has_same_source(self, other: "Function"):
        """Return true if both functions have exactly the same
        source code in their bodies. This doesn't check line numbers
        or source files, just the plain source code for the functions
        """
        if not isinstance(other, Function):
            raise NotImplementedError
        if len(self.bodies) != len(other.bodies):
            return False
        # Compare body parts two by two
        for b1, b2 in zip(
            sorted(self.bodies, key=lambda x: x.start_line),
            sorted(other.bodies, key=lambda x: x.start_line),
        ):
            # If any body differs, functions don't have the same source
            if b1.body != b2.body:
                return False
        return True


@dataclass
class TypeDefinitionType(str, Enum):
    """Enum to store type definition type."""

    STRUCT = "struct"
    UNION = "union"
    ENUM = "enum"
    TYPEDEF = "typedef"
    PREPROC_TYPE = "preproc_type"
    CLASS = "class"


@dataclass
class TypeDefinition:
    """Class to store type definition information."""

    name: str
    """Name of the type."""

    type: TypeDefinitionType
    """Type of the type."""

    definition: str
    """Definition of the type."""

    definition_line: int
    """Line number of the definition of the type (1-based)."""

    file_path: Path
    """Path to the file containing the type definition."""


@dataclass
class TypeUsageInfo:
    """Class to store type usage information."""

    name: str
    """Name of the type being used."""

    file_path: Path
    """Path to the file containing the type usage."""

    line_number: int
    """Line number of the type usage (1-based)."""
