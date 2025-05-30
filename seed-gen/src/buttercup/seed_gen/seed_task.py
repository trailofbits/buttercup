from abc import abstractmethod

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from buttercup.seed_gen.task import BaseTaskState, Task


class SeedBaseTask(Task):
    @abstractmethod
    def _generate_seeds(self, state: BaseTaskState) -> Command:
        """Generate seeds"""
        pass

    @abstractmethod
    def _get_context(self, state: BaseTaskState) -> Command:
        """Get context"""
        pass

    def _build_workflow(self, task_state_cls: type[BaseTaskState]) -> StateGraph:
        """Build the workflow"""
        workflow = StateGraph(task_state_cls)

        workflow.add_node("get_context", self._get_context)

        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)

        workflow.add_node("generate_seeds", self._generate_seeds)

        workflow.add_node("execute_python_funcs", self._execute_python_funcs)

        workflow.set_entry_point("get_context")
        workflow.add_edge("get_context", "tools")

        workflow.add_conditional_edges(
            "tools",
            self._continue_context_retrieval,
            {
                True: "get_context",
                False: "generate_seeds",
            },
        )

        workflow.add_edge("generate_seeds", "execute_python_funcs")
        workflow.add_edge("execute_python_funcs", END)
        return workflow
