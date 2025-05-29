# TypesBundleSubmissionResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**bundle_id** | **str** |  | 
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) | Schema-compliant submissions will only ever receive the statuses accepted or deadline_exceeded | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response import TypesBundleSubmissionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesBundleSubmissionResponse from a JSON string
types_bundle_submission_response_instance = TypesBundleSubmissionResponse.from_json(json)
# print the JSON string representation of the object
print(TypesBundleSubmissionResponse.to_json())

# convert the object into a dict
types_bundle_submission_response_dict = types_bundle_submission_response_instance.to_dict()
# create an instance of TypesBundleSubmissionResponse from a dict
types_bundle_submission_response_from_dict = TypesBundleSubmissionResponse.from_dict(types_bundle_submission_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


