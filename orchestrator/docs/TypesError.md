# TypesError


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**fields** | **Dict[str, str]** |  | [optional] 
**message** | **str** |  | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_error import TypesError

# TODO update the JSON string below
json = "{}"
# create an instance of TypesError from a JSON string
types_error_instance = TypesError.from_json(json)
# print the JSON string representation of the object
print(TypesError.to_json())

# convert the object into a dict
types_error_dict = types_error_instance.to_dict()
# create an instance of TypesError from a dict
types_error_from_dict = TypesError.from_dict(types_error_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


