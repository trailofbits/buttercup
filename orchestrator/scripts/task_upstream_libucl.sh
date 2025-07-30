#!/bin/bash
curl -X 'POST' 'http://127.0.0.1:31326/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "https://github.com/vstakhov/libucl",
    "challenge_repo_head_ref": "8a0294f9eaa4e70342e562cb92792bbe3df90e70",
    "fuzz_tooling_url": "https://github.com/google/oss-fuzz",
    "fuzz_tooling_ref": "master",
    "fuzz_tooling_project_name": "libucl",
    "duration": 1800
}'
