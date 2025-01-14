# TypesPatchSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**description** | **str** | Optional plain text string describing the vulnerability | [optional] 
**patch** | **str** | 100kb Max Size | 
**vuln_id** | **str** |  | 

## Example

```python
from orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesPatchSubmission from a JSON string
types_patch_submission_instance = TypesPatchSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesPatchSubmission.to_json())

# convert the object into a dict
types_patch_submission_dict = types_patch_submission_instance.to_dict()
# create an instance of TypesPatchSubmission from a dict
types_patch_submission_from_dict = TypesPatchSubmission.from_dict(types_patch_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


