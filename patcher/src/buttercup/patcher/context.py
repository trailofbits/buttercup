from pydantic import BaseModel


class ContextCodeSnippet(BaseModel):
    """Code snippet for ContextOutput."""

    file_path: str
    "Path to the vulnerable file, relative to (CP path / 'src')"

    function_name: str | None = None
    "Name of the vulnerable function related to changed_lines"

    code: str | None = None
    "Code of the vulnerable function"

    code_context: str | None = None
    "Additional code context around the vulnerable line/code"
