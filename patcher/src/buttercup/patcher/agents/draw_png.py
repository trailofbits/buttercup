"""Module to visualize the patcher agent state machine."""

from pathlib import Path
from typing import Optional

import graphviz


def draw_state_machine(output_path: Optional[Path] = None) -> None:
    """Draw the patcher agent state machine and save it as a PNG file.

    Args:
        output_path: Optional path where to save the PNG file. If None, saves in current directory.
    """
    # Create a new directed graph
    dot = graphviz.Digraph(comment="Patcher Agent State Machine")
    dot.attr(rankdir="LR")  # Left to right layout

    # Add nodes for each state
    states = [
        "START",
        "INPUT_PROCESSING",
        "FIND_TESTS",
        "INITIAL_CODE_SNIPPET_REQUESTS",
        "ROOT_CAUSE_ANALYSIS",
        "PATCH_STRATEGY",
        "CREATE_PATCH",
        "BUILD_PATCH",
        "RUN_POV",
        "RUN_TESTS",
        "REFLECTION",
        "CONTEXT_RETRIEVER",
        "END",
    ]

    # Add nodes with styling
    for state in states:
        if state == "START":
            dot.node(state, state, shape="oval", style="filled", fillcolor="green")
        elif state == "END":
            dot.node(state, state, shape="oval", style="filled", fillcolor="red")
        else:
            dot.node(state, state, shape="box", style="rounded,filled", fillcolor="lightblue")

    # Add edges to show the flow
    # Start and End transitions
    dot.edge("START", "INPUT_PROCESSING", color="blue", penwidth="2.0")
    dot.edge("RUN_TESTS", "END", color="blue", penwidth="2.0")
    dot.edge("REFLECTION", "END", color="gray")

    # Main flow (colored in blue)
    dot.edge("INPUT_PROCESSING", "FIND_TESTS", color="blue", penwidth="2.0")
    dot.edge("INPUT_PROCESSING", "INITIAL_CODE_SNIPPET_REQUESTS", color="blue", penwidth="2.0")
    dot.edge("FIND_TESTS", "ROOT_CAUSE_ANALYSIS", color="blue", penwidth="2.0")
    dot.edge("INITIAL_CODE_SNIPPET_REQUESTS", "ROOT_CAUSE_ANALYSIS", color="blue", penwidth="2.0")
    dot.edge("ROOT_CAUSE_ANALYSIS", "PATCH_STRATEGY", color="blue", penwidth="2.0")
    dot.edge("PATCH_STRATEGY", "CREATE_PATCH", color="blue", penwidth="2.0")
    dot.edge("CREATE_PATCH", "BUILD_PATCH", color="blue", penwidth="2.0")
    dot.edge("BUILD_PATCH", "RUN_POV", color="blue", penwidth="2.0")
    dot.edge("RUN_POV", "RUN_TESTS", color="blue", penwidth="2.0")

    # Add transitions to REFLECTION (in gray)
    dot.edge("ROOT_CAUSE_ANALYSIS", "REFLECTION", color="gray")
    dot.edge("PATCH_STRATEGY", "REFLECTION", color="gray")
    dot.edge("CREATE_PATCH", "REFLECTION", color="gray")
    dot.edge("BUILD_PATCH", "REFLECTION", color="gray")
    dot.edge("RUN_POV", "REFLECTION", color="gray")
    dot.edge("RUN_TESTS", "REFLECTION", color="gray")

    # Add transitions from REFLECTION (in gray)
    dot.edge("REFLECTION", "ROOT_CAUSE_ANALYSIS", color="gray")
    dot.edge("REFLECTION", "PATCH_STRATEGY", color="gray")
    dot.edge("REFLECTION", "CREATE_PATCH", color="gray")
    dot.edge("REFLECTION", "CONTEXT_RETRIEVER", color="gray")

    # Add transitions from CONTEXT_RETRIEVER (in gray)
    dot.edge("CONTEXT_RETRIEVER", "REFLECTION", color="gray")
    dot.edge("CONTEXT_RETRIEVER", "PATCH_STRATEGY", color="gray")
    dot.edge("CONTEXT_RETRIEVER", "ROOT_CAUSE_ANALYSIS", color="gray")

    # Save the graph
    if output_path is None:
        output_path = Path("patcher_state_machine")
    dot.render(str(output_path), format="png", cleanup=True)


if __name__ == "__main__":
    draw_state_machine()
