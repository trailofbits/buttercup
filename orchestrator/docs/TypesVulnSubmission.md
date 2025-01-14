# TypesVulnSubmission


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**architecture** | **str** |  | 
**data_file** | **str** | 2mb max size | 
**harness_name** | **str** |  | 
**sanitizer** | **str** |  | 
**sarif** | **object** | SARIF Report compliant with \&quot;https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json\&quot; | [optional] 

## Example

```python
from orchestrator.competition_api_client.models.types_vuln_submission import TypesVulnSubmission

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


