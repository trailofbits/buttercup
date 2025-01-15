# litellm
The litellm service proxies all LLMs.

After deploying LiteLLM, you can test it with:
```
curl --location 'http://127.0.0.1:8080/chat/completions' \
--header 'Content-Type: application/json' \
--header "Authorization: Bearer sk-1234" \
--data ' {
      "model": "azure-gpt-4o-mini",
      "messages": [
        {
          "role": "user",
          "content": "explain the color red"
        }
      ]
    }
'
```

Create a virtual key with a budget of 0.01:
```
curl 'http://127.0.0.1:8080/key/generate' \
--header 'Authorization: Bearer sk-1234' \
--header 'Content-Type: application/json' \
--data-raw '{"max_budget": 0.01}' | jq ".key"
```

Use the virtual key in normal requests as the bearer token.
