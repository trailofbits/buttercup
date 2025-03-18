# TypesPatchSubmissionResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**functionality_tests_passing** | **bool** | null indicates the tests have not been run | [optional] 
**patch_id** | **str** |  | 
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) |  | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import TypesPatchSubmissionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesPatchSubmissionResponse from a JSON string
types_patch_submission_response_instance = TypesPatchSubmissionResponse.from_json(json)
# print the JSON string representation of the object
print(TypesPatchSubmissionResponse.to_json())

# convert the object into a dict
types_patch_submission_response_dict = types_patch_submission_response_instance.to_dict()
# create an instance of TypesPatchSubmissionResponse from a dict
types_patch_submission_response_from_dict = TypesPatchSubmissionResponse.from_dict(types_patch_submission_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


