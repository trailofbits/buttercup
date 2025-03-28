import logging
from pathlib import Path

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from buttercup.common.llm import get_langfuse_callbacks
from buttercup.seed_gen.prompts import (
    PYTHON_FUNCTION_LOOKUP_SYSTEM_PROMPT,
    PYTHON_FUNCTION_LOOKUP_USER_PROMPT,
    PYTHON_SEED_EXPLORE_SYSTEM_PROMPT,
    PYTHON_SEED_EXPLORE_USER_PROMPT,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import FunctionRequestList, Task
from buttercup.seed_gen.utils import extract_md

logger = logging.getLogger(__name__)


class SeedExploreState(BaseModel):
    """State for the SeedExplore task."""

    target_function: str = Field(description="The target function to generate seeds for")
    harness: str = Field(description="The harness code")
    collected_functions: dict[str, str] = Field(
        description="Dictionary of collected function definitions"
    )
    iteration: int = Field(description="Current lookup iteration number")
    generated_functions: str = Field(description="The generated seed functions", default=None)


class SeedExploreTask(Task):
    SEED_EXPLORE_SEED_COUNT = 8
    MAX_ITERATIONS = 2
    MAX_LOOKUP_FUNCTIONS = 4

    def _lookup_functions(self, state: SeedExploreState) -> dict:
        """Ask the LLM which functions it would like to understand better"""
        logger.info("Looking up functions")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PYTHON_FUNCTION_LOOKUP_SYSTEM_PROMPT),
                ("human", PYTHON_FUNCTION_LOOKUP_USER_PROMPT),
            ]
        )
        parser = JsonOutputParser(pydantic_object=FunctionRequestList)
        chain = prompt | self.llm | parser
        state_update = {
            "collected_functions": {
                **state.collected_functions,
            },
        }
        additional_functions = "\n\n...\n\n".join(
            f"{body}" for body in state.collected_functions.values()
        )
        try:
            response = chain.invoke(
                {
                    "target_function": state.target_function,
                    "harness": state.harness,
                    "additional_functions": additional_functions,
                    "max_lookup_functions": self.MAX_LOOKUP_FUNCTIONS,
                }
            )

            for func in response[: self.MAX_LOOKUP_FUNCTIONS]:
                func_name = func["name"]
                if func_name in state_update["collected_functions"]:
                    continue

                # Get function definition
                func_def = self._do_get_function_def(func_name, [None])
                if func_def:
                    state_update["collected_functions"][func_name] = func_def.bodies[0].body
                    logger.info(f"Collected function definition for {func_name}")
                else:
                    logger.warning(f"Could not find definition for function {func_name}")

        except Exception as e:
            logger.error("Error during function lookup: %s", str(e))

        state_update["iteration"] = state.iteration + 1
        return state_update

    def _generate_seeds(self, state: SeedExploreState) -> dict:
        """Generate seed functions using collected function definitions"""
        logger.info("Generating seeds")
        state_update = {}
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PYTHON_SEED_EXPLORE_SYSTEM_PROMPT),
                ("human", PYTHON_SEED_EXPLORE_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | extract_md
        chain_config = chain.with_config(RunnableConfig(tags=["seed-explore"]))

        # Format collected functions for prompt
        additional_functions = "\n\n...\n\n".join(
            f"{body}" for body in state.collected_functions.values()
        )

        try:
            funcs = chain_config.invoke(
                {
                    "count": self.SEED_EXPLORE_SEED_COUNT,
                    "harness": state.harness,
                    "target_function": state.target_function,
                    "additional_functions": additional_functions,
                }
            )
            generated_functions = funcs
        except Exception as e:
            logger.error("Error generating seeds: %s", str(e))
            generated_functions = ""

        state_update["generated_functions"] = generated_functions
        return state_update

    def _should_continue(self, state: SeedExploreState) -> bool:
        """Determine if we should continue the iteration"""
        return state.iteration < self.MAX_ITERATIONS

    def generate_seed_funcs(self, harness: str, target_function: str) -> str:
        """Generate a python file of seed-generation functions"""

        state = SeedExploreState(
            target_function=target_function,
            harness=harness,
            collected_functions={},
            iteration=0,
            generated_functions="",
        )

        workflow = StateGraph(SeedExploreState)

        workflow.add_node("lookup_functions", self._lookup_functions)
        workflow.add_node("generate_seeds", self._generate_seeds)
        workflow.set_entry_point("lookup_functions")
        workflow.add_edge("generate_seeds", END)

        workflow.add_conditional_edges(
            "lookup_functions",
            self._should_continue,
            {
                True: "lookup_functions",
                False: "generate_seeds",
            },
        )
        llm_callbacks = get_langfuse_callbacks()
        chain = workflow.compile().with_config(
            RunnableConfig(tags=["seed-explore"], callbacks=llm_callbacks)
        )
        result = chain.invoke(state)

        return result["generated_functions"]

    def do_task(
        self, target_function_name: str, target_function_paths: list[Path], output_dir: Path
    ) -> None:
        """Do seed-explore task"""
        logger.info(
            "Doing seed-explore for challenge %s and function %s (paths: %s)",
            self.package_name,
            target_function_name,
            target_function_paths,
        )
        function_def = self.get_function_def(target_function_name, target_function_paths)
        if not function_def:
            logger.error("No function definition found for %s", target_function_name)
            return
        function_def_body = function_def.bodies[0].body

        harness = self.get_harness_source()
        if harness is None:
            return
        try:
            logger.info(
                "Generating seed functions for challenge %s and target function %s",
                self.package_name,
                target_function_name,
            )
            funcs = self.generate_seed_funcs(harness, function_def_body)
            logger.info("Executing seed functions for challenge %s", self.package_name)
            sandbox_exec_funcs(funcs, output_dir)
        except Exception as err:
            logger.error("Failed seed-explore for challenge %s: %s", self.package_name, str(err))
