#!/bin/bash

seconds=1
minutes=$((60 * $seconds))
hours=$((60 * $minutes))

full_set_duration=$((24 * $hours))
delta_set_duration=$((8 * $hours))

declare -A cc_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-commons-compress.git"
    ["challenge_repo_head_ref"]="challenges/cc-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cc-full-01"
    ["fuzz_tooling_project_name"]="apache-commons-compress"
    ["duration"]=$full_set_duration
)

declare -A cc_delta_02=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-commons-compress.git"
    ["challenge_repo_base_ref"]="154edd0066d1aaf18daafb88253cacbf39017d61"
    ["challenge_repo_head_ref"]="challenges/cc-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cc-delta-02"
    ["fuzz_tooling_project_name"]="apache-commons-compress"
    ["duration"]=$delta_set_duration
)

declare -A cc_delta_03=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-commons-compress.git"
    ["challenge_repo_base_ref"]="6e608498013784abb6878cad7906c2ddc41e45f1"
    ["challenge_repo_head_ref"]="challenges/cc-delta-03"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cc-delta-03"
    ["fuzz_tooling_project_name"]="apache-commons-compress"
    ["duration"]=$delta_set_duration
)

declare -A db_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-dropbear.git"
    ["challenge_repo_head_ref"]="challenges/db-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/db-full-01"
    ["fuzz_tooling_project_name"]="dropbear"
    ["duration"]=$full_set_duration
)

declare -A fp_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-freerdp.git"
    ["challenge_repo_head_ref"]="challenges/fp-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/fp-full-01"
    ["fuzz_tooling_project_name"]="freerdp"
    ["duration"]=$full_set_duration
)

declare -A fp_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-freerdp.git"
    ["challenge_repo_base_ref"]="a92cc0f3ebc3d3f4cf5b6097920a391e9b5fcfcf"
    ["challenge_repo_head_ref"]="challenges/fp-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/fp-delta-01"
    ["fuzz_tooling_project_name"]="freerdp"
    ["duration"]=$delta_set_duration
)

declare -A integration_test_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/integration-test.git"
    ["challenge_repo_base_ref"]="4a714359c60858e3821bd478dc846de1d04dc977"
    ["challenge_repo_head_ref"]="challenges/integration-test-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/integration-test-delta-01"
    ["fuzz_tooling_project_name"]="integration-test"
    ["duration"]=$delta_set_duration
)

declare -A lp_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/example-libpng.git"
    ["challenge_repo_base_ref"]="5bf8da2d7953974e5dfbd778429c3affd461f51a"
    ["challenge_repo_head_ref"]="challenges/lp-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lp-delta-01"
    ["fuzz_tooling_project_name"]="libpng"
    ["duration"]=$delta_set_duration
)

declare -A lx_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_head_ref"]="challenges/lx-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-full-01"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$full_set_duration
)

declare -A lx_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_base_ref"]="39ce264d546f93a0ddb7a1d7987670b8b905c165"
    ["challenge_repo_head_ref"]="challenges/lx-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-delta-01"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$delta_set_duration
)

declare -A lx_delta_02=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_base_ref"]="0f876b983249cd3fb32b53d405f5985e83d8c3bd"
    ["challenge_repo_head_ref"]="challenges/lx-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-delta-02"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$delta_set_duration
)

declare -A lx_full_updated=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_head_ref"]="challenges/lx-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="aixcc-afc"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$full_set_duration
)

declare -A sq_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-sqlite3.git"
    ["challenge_repo_head_ref"]="challenges/sq-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/sq-full-01"
    ["fuzz_tooling_project_name"]="sqlite3"
    ["duration"]=$full_set_duration
)

declare -A sq_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-sqlite3.git"
    ["challenge_repo_base_ref"]="6a3e7f57f00f0a2b6b89b0db7990e3df47175372"
    ["challenge_repo_head_ref"]="challenges/sq-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/sq-delta-01"
    ["fuzz_tooling_project_name"]="sqlite3"
    ["duration"]=$delta_set_duration
)

declare -A zk_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-zookeeper.git"
    ["challenge_repo_head_ref"]="challenges/zk-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/zk-full-01"
    ["fuzz_tooling_project_name"]="zookeeper"
    ["duration"]=$full_set_duration
)

declare -A zk_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-zookeeper.git"
    ["challenge_repo_base_ref"]="f6f34f6d5b6d67205c34de617a0b99fe11e3d323"
    ["challenge_repo_head_ref"]="challenges/zk-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/zk-delta-01"
    ["fuzz_tooling_project_name"]="zookeeper"
    ["duration"]=$delta_set_duration
)

submit_task() {
    task_name=$1
    declare -n task_data_ref=$task_name
    echo $task_name
    echo "${task_data_ref[@]}"
    
    # Convert associative array to JSON
    json_data="{"
    for key in "${!task_data_ref[@]}"; do
        value="${task_data_ref[$key]}"
        # Check if value is numeric (integer)
        if [[ "$value" =~ ^[0-9]+$ ]]; then
            json_data+="\"$key\":$value,"
        else
            json_data+="\"$key\":\"$value\","
        fi
    done
    json_data="${json_data%,}}"  # Remove trailing comma
    
    echo $json_data | jq -C '.'
    curl -X 'POST' 'http://127.0.0.1:31323/webhook/trigger_task' -H 'Content-Type: application/json' -d "$json_data"
}

# From: https://github.com/aixcc-finals/example-crs-architecture/blob/1ccabc62b177a86a49c69a5d3b085eea299223ce/docs/round_info/exhibition-round-2.md#challenge-tasks-archive
sim2() {
    submit_task "fp_full_01"
    submit_task "lx_full_01"
    submit_task "sq_full_01"

    sleep $full_set_duration

    submit_task "cc_full_01"
    submit_task "zk_full_01"
    submit_task "db_full_01"

    sleep $full_set_duration

    submit_task "fp_delta_01"
    submit_task "lx_delta_02"
    submit_task "integration_test_delta_01"
    submit_task "lp_delta_01"

    sleep $delta_set_duration

    submit_task "sq_delta_01"
    submit_task "lx_delta_01"

    sleep $delta_set_duration

    submit_task "zk_delta_01"
    submit_task "cc_delta_02"
    submit_task "cc_delta_03"

    sleep $delta_set_duration
}

all2() {
    submit_task "cc_full_01"
    submit_task "db_full_01"
    submit_task "fp_full_01"
    submit_task "integration_test_delta_01"
    submit_task "lp_delta_01"
    submit_task "lx_full_01"
    submit_task "sq_full_01"
    submit_task "zk_full_01"
}

single() {
    submit_task "$1"
}

usage() {
    echo "Usage: $0 [sim2|all2|single <name>]"
    echo ""
    echo "sim2          = Simulate round 2."
    echo "all2          = Run one challenge from each repository."
    echo "single <name> = Run one challenge."
    echo ""
    echo "name = The name of the challenge to run:"
    echo "  cc_full_01 | cc_delta_02 | cc_delta_03"
    echo "  db_full_01"
    echo "  fp_full_01 | fp_delta_01"
    echo "  integration_test_delta_01"
    echo "  lp_delta_01"
    echo "  lx_full_01 | lx_delta_01 | lx_delta_02"
    echo "  sq_full_01 | sq_delta_01"
    echo "  zk_full_01 | zk_delta_01"
    echo ""
    echo "  lx_full_updated -> using the most recent version of helper.py"
}

main() {
    if [ $# -eq 0 ]; then
        usage
        exit 1
    fi

    case "$1" in
        "sim2")
            sim2
            ;;
        "all2")
            all2
            ;;
        "single")
            if [ -z "$2" ]; then
                usage
                exit 1
            fi
            single "$2"
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
