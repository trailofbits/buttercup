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

## OrcaRouter

[OrcaRouter](https://www.orcarouter.ai) is an OpenAI-compatible AI gateway that
routes many providers behind one endpoint. It is registered in
`litellm_config.yaml` (and the mirrored `deployment/k8s/values.yaml` list) under
its own name, with its own credential — it does not reuse `OPENAI_API_KEY`,
derives nothing from the OpenAI base URL, and is not a generic custom-endpoint
option:

| LiteLLM model name | Upstream model | Notes |
| --- | --- | --- |
| `orcarouter-orcacyber-zero` | `orcacyber-zero` | Recommended default for authorized security work; needs business verification on the OrcaRouter side |
| `orcarouter-auto` | `orcarouter/auto` | Gateway picks the upstream model |
| `orcarouter-deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | |
| `orcarouter-deepseek-v4-flash` | `deepseek/deepseek-v4-flash` | |

OrcaCyber Zero is aimed at security teams that have completed business
verification, and it allows authorized security work that general-purpose
gateways often refuse.

Set `ORCAROUTER_API_KEY` (prefix `sk-orca-`) in the LiteLLM environment; keys are
managed at https://www.orcarouter.ai/api/v1/auth/keys. Without it the
`orcarouter-*` entries return an authentication error and every other provider is
unaffected. The model catalog is available at
`GET https://api.orcarouter.ai/v1/models?capability=chat`; the dashboard's
provider panel reads it through `buttercup.common.orcarouter` and only offers
models whose `supported_endpoint_types` include a dialect this client speaks.
