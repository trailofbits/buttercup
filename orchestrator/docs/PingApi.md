# competition_api_client.PingApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**v1_ping_get**](PingApi.md#v1_ping_get) | **GET** /v1/ping/ | Test authentication creds and network connectivity


# **v1_ping_get**
> TypesPingResponse v1_ping_get()

Test authentication creds and network connectivity

Test authentication creds and network connectivity

### Example

* Basic Authentication (BasicAuth):

```python
import competition_api_client
from buttercup.orchestrator.competition_api_client.models.types_ping_response import TypesPingResponse
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
    api_instance = competition_api_client.PingApi(api_client)

    try:
        # Test authentication creds and network connectivity
        api_response = api_instance.v1_ping_get()
        print("The response of PingApi->v1_ping_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PingApi->v1_ping_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**TypesPingResponse**](TypesPingResponse.md)

### Authorization

[BasicAuth](../README.md#BasicAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: */*

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | OK |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

