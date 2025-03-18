# TypesPatchSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**patch** | **str** | Base64 encoded patch in unified diff format  100KiB max size before Base64 encoding | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission

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


