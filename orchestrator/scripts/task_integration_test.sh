#!/bin/bash
curl -X 'POST' 'http://127.0.0.1:31323/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "https://github.com/tob-challenges/integration-test.git",
    "challenge_repo_base_ref": "4a714359c60858e3821bd478dc846de1d04dc977",
    "challenge_repo_head_ref": "challenges/integration-test-delta-01",
    "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc",
    "fuzz_tooling_ref": "ffa771deda2156995e80f76107f90dec14218b7b",
    "fuzz_tooling_project_name": "integration-test",
    "duration": 1800
}'
