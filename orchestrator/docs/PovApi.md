# competition_api_client.PovApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_task_task_id_pov_post**](PovApi.md#v1_task_task_id_pov_post) | **POST** /v1/task/{task_id}/pov/ | Submit Vulnerability
[**v1_task_task_id_pov_pov_id_get**](PovApi.md#v1_task_task_id_pov_pov_id_get) | **GET** /v1/task/{task_id}/pov/{pov_id}/ | Vulnerability Status


# **v1_task_task_id_pov_post**
> TypesPOVSubmissionResponse v1_task_task_id_pov_post(task_id, payload)

Submit Vulnerability

submit a vulnerability for testing

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_pov_submission import TypesPOVSubmission
from buttercup.orchestrator.competition_api_client.models.types_pov_submission_response import TypesPOVSubmissionResponse
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
    api_instance = competition_api_client.PovApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    payload = competition_api_client.TypesPOVSubmission() # TypesPOVSubmission | Submission body

    try:
        # Submit Vulnerability
        api_response = api_instance.v1_task_task_id_pov_post(task_id, payload)
        print("The response of PovApi->v1_task_task_id_pov_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PovApi->v1_task_task_id_pov_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **payload** | [**TypesPOVSubmission**](TypesPOVSubmission.md)| Submission body | 

### Return type

[**TypesPOVSubmissionResponse**](TypesPOVSubmissionResponse.md)

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

# **v1_task_task_id_pov_pov_id_get**
> TypesPOVSubmissionResponse v1_task_task_id_pov_pov_id_get(task_id, pov_id)

Vulnerability Status

yield the status of vuln testing

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_pov_submission_response import TypesPOVSubmissionResponse
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
    api_instance = competition_api_client.PovApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    pov_id = 'pov_id_example' # str | POV ID

    try:
        # Vulnerability Status
        api_response = api_instance.v1_task_task_id_pov_pov_id_get(task_id, pov_id)
        print("The response of PovApi->v1_task_task_id_pov_pov_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PovApi->v1_task_task_id_pov_pov_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **pov_id** | **str**| POV ID | 

### Return type

[**TypesPOVSubmissionResponse**](TypesPOVSubmissionResponse.md)

### Authorization

[BasicAuth](../README.md#BasicAuth)

### HTTP request headers

 - **Content-Type**: Not defined
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

