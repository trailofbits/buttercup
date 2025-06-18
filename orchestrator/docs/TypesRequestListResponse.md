# TypesRequestListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**challenges** | **List[str]** | List of challenges that competitors may task themselves with | 

## Example

```python
from buttercup.orchestrator.competition_api_client.models.types_request_list_response import TypesRequestListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TypesRequestListResponse from a JSON string
types_request_list_response_instance = TypesRequestListResponse.from_json(json)
# print the JSON string representation of the object
print(TypesRequestListResponse.to_json())

# convert the object into a dict
types_request_list_response_dict = types_request_list_response_instance.to_dict()
# create an instance of TypesRequestListResponse from a dict
types_request_list_response_from_dict = TypesRequestListResponse.from_dict(types_request_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


