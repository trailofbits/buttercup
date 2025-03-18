# TypesSARIFSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**sarif** | **object** | SARIF object compliant with the provided schema | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_sarif_submission import TypesSARIFSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesSARIFSubmission from a JSON string
types_sarif_submission_instance = TypesSARIFSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesSARIFSubmission.to_json())

# convert the object into a dict
types_sarif_submission_dict = types_sarif_submission_instance.to_dict()
# create an instance of TypesSARIFSubmission from a dict
types_sarif_submission_from_dict = TypesSARIFSubmission.from_dict(types_sarif_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


