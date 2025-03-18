# competition_api_client.BroadcastSarifAssessmentApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post**](BroadcastSarifAssessmentApi.md#v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post) | **POST** /v1/task/{task_id}/broadcast-sarif-assessment/{broadcast_sarif_id}/ | Submit a SARIF Assessment


# **v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post**
> TypesSarifAssessmentResponse v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post(task_id, broadcast_sarif_id, payload)

Submit a SARIF Assessment

Submit a SARIF assessment

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_sarif_assessment_response import TypesSarifAssessmentResponse
from buttercup.orchestrator.competition_api_client.models.types_sarif_assessment_submission import TypesSarifAssessmentSubmission
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
    api_instance = competition_api_client.BroadcastSarifAssessmentApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    broadcast_sarif_id = 'broadcast_sarif_id_example' # str | Broadcast SARIF ID
    payload = competition_api_client.TypesSarifAssessmentSubmission() # TypesSarifAssessmentSubmission | Submission body

    try:
        # Submit a SARIF Assessment
        api_response = api_instance.v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post(task_id, broadcast_sarif_id, payload)
        print("The response of BroadcastSarifAssessmentApi->v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BroadcastSarifAssessmentApi->v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **broadcast_sarif_id** | **str**| Broadcast SARIF ID | 
 **payload** | [**TypesSarifAssessmentSubmission**](TypesSarifAssessmentSubmission.md)| Submission body | 

### Return type

[**TypesSarifAssessmentResponse**](TypesSarifAssessmentResponse.md)

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

