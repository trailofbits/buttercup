# TypesSarifAssessmentResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**TypesSubmissionStatus**](TypesSubmissionStatus.md) |  | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_sarif_assessment_response import TypesSarifAssessmentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesSarifAssessmentResponse from a JSON string
types_sarif_assessment_response_instance = TypesSarifAssessmentResponse.from_json(json)
# print the JSON string representation of the object
print(TypesSarifAssessmentResponse.to_json())

# convert the object into a dict
types_sarif_assessment_response_dict = types_sarif_assessment_response_instance.to_dict()
# create an instance of TypesSarifAssessmentResponse from a dict
types_sarif_assessment_response_from_dict = TypesSarifAssessmentResponse.from_dict(types_sarif_assessment_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


