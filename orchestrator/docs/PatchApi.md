# competition_api_client.PatchApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_task_task_id_patch_patch_id_get**](PatchApi.md#v1_task_task_id_patch_patch_id_get) | **GET** /v1/task/{task_id}/patch/{patch_id}/ | Patch Status
[**v1_task_task_id_patch_post**](PatchApi.md#v1_task_task_id_patch_post) | **POST** /v1/task/{task_id}/patch/ | Submit Patch


# **v1_task_task_id_patch_patch_id_get**
> TypesPatchSubmissionResponse v1_task_task_id_patch_patch_id_get(task_id, patch_id)

Patch Status

yield the status of patch testing

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import TypesPatchSubmissionResponse
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
    api_instance = competition_api_client.PatchApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    patch_id = 'patch_id_example' # str | Patch ID

    try:
        # Patch Status
        api_response = api_instance.v1_task_task_id_patch_patch_id_get(task_id, patch_id)
        print("The response of PatchApi->v1_task_task_id_patch_patch_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PatchApi->v1_task_task_id_patch_patch_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **patch_id** | **str**| Patch ID | 

### Return type

[**TypesPatchSubmissionResponse**](TypesPatchSubmissionResponse.md)

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

# **v1_task_task_id_patch_post**
> TypesPatchSubmissionResponse v1_task_task_id_patch_post(task_id, payload)

Submit Patch

submit a patch for testing

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import TypesPatchSubmissionResponse
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
    api_instance = competition_api_client.PatchApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    payload = competition_api_client.TypesPatchSubmission() # TypesPatchSubmission | Payload

    try:
        # Submit Patch
        api_response = api_instance.v1_task_task_id_patch_post(task_id, payload)
        print("The response of PatchApi->v1_task_task_id_patch_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PatchApi->v1_task_task_id_patch_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **payload** | [**TypesPatchSubmission**](TypesPatchSubmission.md)| Payload | 

### Return type

[**TypesPatchSubmissionResponse**](TypesPatchSubmissionResponse.md)

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

