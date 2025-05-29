# TypesRequestSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**duration_secs** | **int** | Time in seconds until a task should expire. If not provided, defaults to 3600. | [optional] 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_request_submission import TypesRequestSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesRequestSubmission from a JSON string
types_request_submission_instance = TypesRequestSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesRequestSubmission.to_json())

# convert the object into a dict
types_request_submission_dict = types_request_submission_instance.to_dict()
# create an instance of TypesRequestSubmission from a dict
types_request_submission_from_dict = TypesRequestSubmission.from_dict(types_request_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


