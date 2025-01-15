# litellm
The litellm service proxies all LLMs.

After deploying LiteLLM, you can test it with:
```
curl --location 'http://127.0.0.1:8080/chat/completions' --header 'Content-Type: application/json' --data ' {
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
