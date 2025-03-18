# competition_api_client.FeeformApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_task_task_id_freeform_post**](FeeformApi.md#v1_task_task_id_freeform_post) | **POST** /v1/task/{task_id}/freeform/ | Submit Freeform


# **v1_task_task_id_freeform_post**
> TypesFreeformResponse v1_task_task_id_freeform_post(task_id, payload)

Submit Freeform

submits a freeform pov

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_freeform_response import TypesFreeformResponse
from buttercup.orchestrator.competition_api_client.models.types_freeform_submission import TypesFreeformSubmission
from buttercup.orchestrator.competition_api_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = competition_api_client.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure HTTP basic authorization: BasicAuth
configuration = competition_api_client.Configuration(
    username = os.environ["USERNAME"],
    password = os.environ["PASSWORD"]
)

# Enter a context with an instance of the API client
with competition_api_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = competition_api_client.FeeformApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    payload = competition_api_client.TypesFreeformSubmission() # TypesFreeformSubmission | Submission Body

    try:
        # Submit Freeform
        api_response = api_instance.v1_task_task_id_freeform_post(task_id, payload)
        print("The response of FeeformApi->v1_task_task_id_freeform_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling FeeformApi->v1_task_task_id_freeform_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **payload** | [**TypesFreeformSubmission**](TypesFreeformSubmission.md)| Submission Body | 

### Return type

[**TypesFreeformResponse**](TypesFreeformResponse.md)

### Authorization

[BasicAuth](../README.md#BasicAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | OK |  -  |
**400** | Bad Request |  -  |
**401** | Unauthorized |  -  |
**404** | Not Found |  -  |
**500** | Internal Server Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

