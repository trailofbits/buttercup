# TypesPOVSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**architecture** | [**TypesArchitecture**](TypesArchitecture.md) |  | 
**engine** | [**TypesFuzzingEngine**](TypesFuzzingEngine.md) |  | 
**fuzzer_name** | **str** | Fuzz Tooling fuzzer that exercises this vuln  4KiB max size | 
**sanitizer** | **str** | Fuzz Tooling Sanitizer that exercises this vuln  4KiB max size | 
**testcase** | **str** | Base64 encoded vuln trigger  2MiB max size before Base64 encoding | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_pov_submission import TypesPOVSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesPOVSubmission from a JSON string
types_pov_submission_instance = TypesPOVSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesPOVSubmission.to_json())

# convert the object into a dict
types_pov_submission_dict = types_pov_submission_instance.to_dict()
# create an instance of TypesPOVSubmission from a dict
types_pov_submission_from_dict = TypesPOVSubmission.from_dict(types_pov_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


