# competition_api_client.BundleApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_task_task_id_bundle_bundle_id_delete**](BundleApi.md#v1_task_task_id_bundle_bundle_id_delete) | **DELETE** /v1/task/{task_id}/bundle/{bundle_id}/ | Delete Bundle
[**v1_task_task_id_bundle_bundle_id_get**](BundleApi.md#v1_task_task_id_bundle_bundle_id_get) | **GET** /v1/task/{task_id}/bundle/{bundle_id}/ | Get Bundle
[**v1_task_task_id_bundle_bundle_id_patch**](BundleApi.md#v1_task_task_id_bundle_bundle_id_patch) | **PATCH** /v1/task/{task_id}/bundle/{bundle_id}/ | Update Bundle
[**v1_task_task_id_bundle_post**](BundleApi.md#v1_task_task_id_bundle_post) | **POST** /v1/task/{task_id}/bundle/ | Submit Bundle


# **v1_task_task_id_bundle_bundle_id_delete**
> str v1_task_task_id_bundle_bundle_id_delete(task_id, bundle_id)

Delete Bundle

delete a bundle

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
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
    api_instance = competition_api_client.BundleApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    bundle_id = 'bundle_id_example' # str | Bundle ID

    try:
        # Delete Bundle
        api_response = api_instance.v1_task_task_id_bundle_bundle_id_delete(task_id, bundle_id)
        print("The response of BundleApi->v1_task_task_id_bundle_bundle_id_delete:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BundleApi->v1_task_task_id_bundle_bundle_id_delete: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **bundle_id** | **str**| Bundle ID | 

### Return type

**str**

### Authorization

[BasicAuth](../README.md#BasicAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | No Content |  -  |
**400** | Bad Request |  -  |
**401** | Unauthorized |  -  |
**404** | Not Found |  -  |
**500** | Internal Server Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **v1_task_task_id_bundle_bundle_id_get**
> TypesBundleSubmissionResponseVerbose v1_task_task_id_bundle_bundle_id_get(task_id, bundle_id)

Get Bundle

get a bundle

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response_verbose import TypesBundleSubmissionResponseVerbose
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
    api_instance = competition_api_client.BundleApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    bundle_id = 'bundle_id_example' # str | Bundle ID

    try:
        # Get Bundle
        api_response = api_instance.v1_task_task_id_bundle_bundle_id_get(task_id, bundle_id)
        print("The response of BundleApi->v1_task_task_id_bundle_bundle_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BundleApi->v1_task_task_id_bundle_bundle_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **bundle_id** | **str**| Bundle ID | 

### Return type

[**TypesBundleSubmissionResponseVerbose**](TypesBundleSubmissionResponseVerbose.md)

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

# **v1_task_task_id_bundle_bundle_id_patch**
> TypesBundleSubmissionResponseVerbose v1_task_task_id_bundle_bundle_id_patch(task_id, bundle_id, payload)

Update Bundle

updates a bundle

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response_verbose import TypesBundleSubmissionResponseVerbose
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
    api_instance = competition_api_client.BundleApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    bundle_id = 'bundle_id_example' # str | Bundle ID
    payload = competition_api_client.TypesBundleSubmission() # TypesBundleSubmission | Submission Body

    try:
        # Update Bundle
        api_response = api_instance.v1_task_task_id_bundle_bundle_id_patch(task_id, bundle_id, payload)
        print("The response of BundleApi->v1_task_task_id_bundle_bundle_id_patch:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BundleApi->v1_task_task_id_bundle_bundle_id_patch: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **bundle_id** | **str**| Bundle ID | 
 **payload** | [**TypesBundleSubmission**](TypesBundleSubmission.md)| Submission Body | 

### Return type

[**TypesBundleSubmissionResponseVerbose**](TypesBundleSubmissionResponseVerbose.md)

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

# **v1_task_task_id_bundle_post**
> TypesBundleSubmissionResponse v1_task_task_id_bundle_post(task_id, payload)

Submit Bundle

submits a bundle

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response import TypesBundleSubmissionResponse
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
    api_instance = competition_api_client.BundleApi(api_client)
    task_id = 'task_id_example' # str | Task ID
    payload = competition_api_client.TypesBundleSubmission() # TypesBundleSubmission | Submission Body

    try:
        # Submit Bundle
        api_response = api_instance.v1_task_task_id_bundle_post(task_id, payload)
        print("The response of BundleApi->v1_task_task_id_bundle_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BundleApi->v1_task_task_id_bundle_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **task_id** | **str**| Task ID | 
 **payload** | [**TypesBundleSubmission**](TypesBundleSubmission.md)| Submission Body | 

### Return type

[**TypesBundleSubmissionResponse**](TypesBundleSubmissionResponse.md)

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

