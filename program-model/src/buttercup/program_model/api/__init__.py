"""Program Model APIs."""

__version__ = "0.0.1"
__module_name__ = "program_model_api"

from program_model.api.getters import get_graph, get_function, get_struct
from program_model.api.setters import set_label

__all__ = [
    "get_graph",
    "get_function",
    "get_struct",
    "set_label",
]
