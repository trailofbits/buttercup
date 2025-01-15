# litellm
The litellm service proxies all LLMs.

## Running litellm
Copy `env.template` to `.env` and set API variables for the APIs you will use.

Start the service locally with:
```
docker compose -f docker-compose.litellm.yaml up -d
```

Test litellm with:
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

Stop the service with:
```
docker compose -f docker-compose.litellm.yaml down
```
