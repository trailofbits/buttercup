#!/bin/bash
curl -X 'POST' 'http://127.0.0.1:31323/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "https://github.com/tob-challenges/example-libpng",
    "challenge_repo_base_ref": "5bf8da2d7953974e5dfbd778429c3affd461f51a",
    "challenge_repo_head_ref": "challenges/lp-delta-01",
    "fuzz_tooling_url": "https://github.com/google/oss-fuzz",
    "fuzz_tooling_ref": "master",
    "fuzz_tooling_project_name": "libpng",
    "duration": 1800
}'
