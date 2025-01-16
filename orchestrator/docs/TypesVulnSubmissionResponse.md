# TypesVulnSubmissionResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) |  | 
**vuln_id** | **str** |  | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_vuln_submission_response import TypesVulnSubmissionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesVulnSubmissionResponse from a JSON string
types_vuln_submission_response_instance = TypesVulnSubmissionResponse.from_json(json)
# print the JSON string representation of the object
print(TypesVulnSubmissionResponse.to_json())

# convert the object into a dict
types_vuln_submission_response_dict = types_vuln_submission_response_instance.to_dict()
# create an instance of TypesVulnSubmissionResponse from a dict
types_vuln_submission_response_from_dict = TypesVulnSubmissionResponse.from_dict(types_vuln_submission_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


