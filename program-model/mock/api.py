from buttercup.program_model.api import Graph
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
        nodes = graph.get_nodes_by_text("png_read_filter_row_up_mmi")

        if nodes:
            logger.info(f"Found {len(nodes)} nodes")
            for node in nodes:
                logger.info(node.id)
                logger.info(node.label)
                logger.info(node.property.keys())
        else:
            logger.info("No nodes found")


if __name__ == "__main__":
    main()
