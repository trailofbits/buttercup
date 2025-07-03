#!/bin/bash
curl -X 'POST' 'http://127.0.0.1:31323/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "https://github.com/pnggroup/libpng",
    "challenge_repo_head_ref": "libpng16",
    "fuzz_tooling_url": "https://github.com/google/oss-fuzz",
    "fuzz_tooling_ref": "master",
    "fuzz_tooling_project_name": "libpng",
    "duration": 1800
}'
