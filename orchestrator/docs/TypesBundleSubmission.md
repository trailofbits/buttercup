# TypesBundleSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**broadcast_sarif_id** | **str** |  | [optional] 
**description** | **str** | optional plaintext description of the components of the bundle, such as would be found in a pull request description or bug report | [optional] 
**freeform_id** | **str** |  | [optional] 
**patch_id** | **str** |  | [optional] 
**pov_id** | **str** |  | [optional] 
**submitted_sarif_id** | **str** |  | [optional] 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesBundleSubmission from a JSON string
types_bundle_submission_instance = TypesBundleSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesBundleSubmission.to_json())

# convert the object into a dict
types_bundle_submission_dict = types_bundle_submission_instance.to_dict()
# create an instance of TypesBundleSubmission from a dict
types_bundle_submission_from_dict = TypesBundleSubmission.from_dict(types_bundle_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


