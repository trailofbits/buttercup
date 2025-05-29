# competition_api_client.RequestApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_request_delta_post**](RequestApi.md#v1_request_delta_post) | **POST** /v1/request/delta/ | Send a delta task to the source of this request


# **v1_request_delta_post**
> TypesMessage v1_request_delta_post(payload)

Send a delta task to the source of this request

Send a delta task to the source of this request

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_message import TypesMessage
from buttercup.orchestrator.competition_api_client.models.types_request_submission import TypesRequestSubmission
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
    api_instance = competition_api_client.RequestApi(api_client)
    payload = competition_api_client.TypesRequestSubmission() # TypesRequestSubmission | Submission Body

    try:
        # Send a delta task to the source of this request
        api_response = api_instance.v1_request_delta_post(payload)
        print("The response of RequestApi->v1_request_delta_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RequestApi->v1_request_delta_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **payload** | [**TypesRequestSubmission**](TypesRequestSubmission.md)| Submission Body | 

### Return type

[**TypesMessage**](TypesMessage.md)

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

