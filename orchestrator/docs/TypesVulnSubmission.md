# TypesVulnSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**architecture** | [**TypesArchitecture**](TypesArchitecture.md) |  | 
**data_file** | **str** | Base64 encoded vuln trigger  2MiB max size before Base64 encoding | 
**harness_name** | **str** | Fuzz Tooling Harness Name that exercises this vuln  4KiB max size | 
**sanitizer** | **str** | Fuzz Tooling Sanitizer that exercises this vuln  4KiB max size | 
**sarif** | **object** | Optional SARIF Report compliant with the provided versioned SARIF schema | [optional] 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_vuln_submission import TypesVulnSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of TypesVulnSubmission from a JSON string
types_vuln_submission_instance = TypesVulnSubmission.from_json(json)
# print the JSON string representation of the object
print(TypesVulnSubmission.to_json())

# convert the object into a dict
types_vuln_submission_dict = types_vuln_submission_instance.to_dict()
# create an instance of TypesVulnSubmission from a dict
types_vuln_submission_from_dict = TypesVulnSubmission.from_dict(types_vuln_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


