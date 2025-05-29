# TypesSARIFSubmissionResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) | Schema-compliant submissions will only ever receive the statuses accepted or deadline_exceeded | 
**submitted_sarif_id** | **str** |  | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_sarif_submission_response import TypesSARIFSubmissionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesSARIFSubmissionResponse from a JSON string
types_sarif_submission_response_instance = TypesSARIFSubmissionResponse.from_json(json)
# print the JSON string representation of the object
print(TypesSARIFSubmissionResponse.to_json())

# convert the object into a dict
types_sarif_submission_response_dict = types_sarif_submission_response_instance.to_dict()
# create an instance of TypesSARIFSubmissionResponse from a dict
types_sarif_submission_response_from_dict = TypesSARIFSubmissionResponse.from_dict(types_sarif_submission_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


