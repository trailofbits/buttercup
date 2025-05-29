# TypesMessage


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**message** | **str** |  | [optional] 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_message import TypesMessage

# TODO update the JSON string below
json = "{}"
# create an instance of TypesMessage from a JSON string
types_message_instance = TypesMessage.from_json(json)
# print the JSON string representation of the object
print(TypesMessage.to_json())

# convert the object into a dict
types_message_dict = types_message_instance.to_dict()
# create an instance of TypesMessage from a dict
types_message_from_dict = TypesMessage.from_dict(types_message_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


