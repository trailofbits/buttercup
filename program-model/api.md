# Program Model API

Kythe [schema](https://kythe.io/docs/schema/).

## Getters

`get_function_body(source_path: Path | None, function_name: str) -> List[str]`: Get function body(s) by name.

`get_distinct_edge_types() -> List[str]`: Get distinct edge types.

`get_distinct_node_types() -> List[Node]`: Get distinct node types.

## Setters

`set_node_property(node: Node, property_name: str, property_value: str) -> bool`: Set a property on a node.

`set_edge_property(edge: Edge, property_name: str, property_value: str) -> bool`: Set a property on an edge.

## Example Usage

```shell
cd afc-crs-trail-of-bits/program-model

uv run mock/api.py
```
