# TypesBundleSubmissionResponseVerbose


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**broadcast_sarif_id** | **str** |  | [optional] 
**bundle_id** | **str** |  | 
**description** | **str** |  | [optional] 
**freeform_id** | **str** |  | [optional] 
**patch_id** | **str** |  | [optional] 
**pov_id** | **str** |  | [optional] 
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) | Schema-compliant submissions will only ever receive the statuses accepted or deadline_exceeded | 
**submitted_sarif_id** | **str** |  | [optional] 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response_verbose import TypesBundleSubmissionResponseVerbose

# TODO update the JSON string below
json = "{}"
# create an instance of TypesBundleSubmissionResponseVerbose from a JSON string
types_bundle_submission_response_verbose_instance = TypesBundleSubmissionResponseVerbose.from_json(json)
# print the JSON string representation of the object
print(TypesBundleSubmissionResponseVerbose.to_json())

# convert the object into a dict
types_bundle_submission_response_verbose_dict = types_bundle_submission_response_verbose_instance.to_dict()
# create an instance of TypesBundleSubmissionResponseVerbose from a dict
types_bundle_submission_response_verbose_from_dict = TypesBundleSubmissionResponseVerbose.from_dict(types_bundle_submission_response_verbose_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


