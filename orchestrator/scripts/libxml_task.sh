#!/bin/bash
curl -X 'POST' 'http://127.0.0.1:31323/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "git@github.com:aixcc-finals/afc-libxml2.git",
    "challenge_repo_base_ref": "792cc4a1462d4a969d9d38bd80a52d2e4f7bd137",
    "challenge_repo_head_ref": "9d1cb67c31933ee5ae3ee458940f7dbeb2fde8b8",
    "fuzz_tooling_url": "git@github.com:aixcc-finals/oss-fuzz-aixcc.git",
    "fuzz_tooling_ref": "challenge-state/lx-ex1-delta-01",
    "fuzz_tooling_project_name": "libxml2",
    "harnesses_included": true,
    "duration": 1800
}'
