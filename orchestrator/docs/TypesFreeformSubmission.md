# TypesFreeformSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**submission** | **str** | Base64 encoded arbitrary data  2MiB max size before Base64 encoding |

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_freeform_submission import TypesFreeformSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesFreeformSubmission from a JSON string
types_freeform_submission_instance = TypesFreeformSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesFreeformSubmission.to_json())

# convert the object into a dict
types_freeform_submission_dict = types_freeform_submission_instance.to_dict()
# create an instance of TypesFreeformSubmission from a dict
types_freeform_submission_from_dict = TypesFreeformSubmission.from_dict(types_freeform_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
