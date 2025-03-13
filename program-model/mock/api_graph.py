from buttercup.program_model.api import Graph
from pathlib import Path
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
    ],
)


def main():
    with Graph(url="ws://localhost:8182/gremlin") as graph:
        #       # Get examples of each type of node
        #       logger.info("Getting examples of each type of node")
        #       nodes = graph.get_distinct_node_types()
        #       logger.info(f"Found {len(nodes)} distinct node types")
        #       for node in nodes:
        #           logger.info(node)
        #           logger.info("=" * 80)

        #       # Get examples of each type of edge
        #       logger.info("Getting examples of each type of edge")
        #       edges = graph.get_distinct_edge_types()
        #       logger.info(f"Found {len(edges)} distinct edge types")
        #       for edge in edges:
        #           logger.info(edge)
        #           logger.info("=" * 80)

        function_name = "png_handle_iCCP"
        file_path = Path("pngrutil.c")

        logger.info(f"Getting function bodies with name: {function_name}")
        bodies = graph.get_function_body(function_name)
        if not bodies:
            logger.info("No bodies found")
        for body in bodies:
            logger.info(body)
            logger.info("=" * 80)

        logger.info(
            f"Getting function bodies with name '{function_name}' from file path '{file_path}'"
        )
        bodies = graph.get_function_body(
            function_name=function_name, source_path=file_path
        )
        if not bodies:
            logger.info("No bodies found")
        for body in bodies:
            logger.info(body)
            logger.info("=" * 80)

        file_path = Path("pngmem.c")

        logger.info(
            f"Getting function bodies with name '{function_name}' from file path '{file_path}'"
        )
        bodies = graph.get_function_body(
            function_name=function_name, source_path=file_path
        )
        if not bodies:
            logger.info("No bodies found")
        for body in bodies:
            logger.info(body)
            logger.info("=" * 80)


if __name__ == "__main__":
    main()
