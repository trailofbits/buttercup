# TypesPOVSubmissionResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**pov_id** | **str** |  | 
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) |  | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_pov_submission_response import TypesPOVSubmissionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesPOVSubmissionResponse from a JSON string
types_pov_submission_response_instance = TypesPOVSubmissionResponse.from_json(json)
# print the JSON string representation of the object
print(TypesPOVSubmissionResponse.to_json())

# convert the object into a dict
types_pov_submission_response_dict = types_pov_submission_response_instance.to_dict()
# create an instance of TypesPOVSubmissionResponse from a dict
types_pov_submission_response_from_dict = TypesPOVSubmissionResponse.from_dict(types_pov_submission_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


