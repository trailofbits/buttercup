# TypesFreeformResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**freeform_id** | **str** |  | 
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) | Schema-compliant submissions will only ever receive the statuses accepted or deadline_exceeded | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_freeform_response import TypesFreeformResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesFreeformResponse from a JSON string
types_freeform_response_instance = TypesFreeformResponse.from_json(json)
# print the JSON string representation of the object
print(TypesFreeformResponse.to_json())

# convert the object into a dict
types_freeform_response_dict = types_freeform_response_instance.to_dict()
# create an instance of TypesFreeformResponse from a dict
types_freeform_response_from_dict = TypesFreeformResponse.from_dict(types_freeform_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


