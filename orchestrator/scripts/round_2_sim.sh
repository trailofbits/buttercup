#!/bin/bash

seconds=1
minutes=$((60 * $seconds))
hours=$((60 * $minutes))

full_set_duration=$((24 * $hours))
delta_set_duration=$((8 * $hours))

declare -A freerdp_full=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-freerdp.git"
    ["challenge_repo_head_ref"]="challenges/fp-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/fp-full-01"
    ["fuzz_tooling_project_name"]="freerdp"
    ["duration"]=$full_set_duration
)

declare -A libxml2_full=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_head_ref"]="challenges/lx-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-full-01"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$full_set_duration
)

declare -A sqlite_full=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-sqlite3.git"
    ["challenge_repo_head_ref"]="challenges/sq-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/sq-full-01"
    ["fuzz_tooling_project_name"]="sqlite3"
    ["duration"]=$full_set_duration
)

declare -A commons_compress_full=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-commons-compress.git"
    ["challenge_repo_head_ref"]="challenges/cc-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cc-full-01"
    ["fuzz_tooling_project_name"]="apache-commons-compress"
    ["duration"]=$full_set_duration
)

declare -A zookeeper_full=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-zookeeper.git"
    ["challenge_repo_head_ref"]="challenges/zk-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/zk-full-01"
    ["fuzz_tooling_project_name"]="zookeeper"
    ["duration"]=$full_set_duration
)

declare -A dropbear_full=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-dropbear.git"
    ["challenge_repo_head_ref"]="challenges/db-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/db-full-01"
    ["fuzz_tooling_project_name"]="dropbear"
    ["duration"]=$full_set_duration
)

declare -A freerdp_delta_1=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-freerdp.git"
    ["challenge_repo_base_ref"]="a92cc0f3ebc3d3f4cf5b6097920a391e9b5fcfcf"
    ["challenge_repo_head_ref"]="challenges/fp-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/fp-delta-01"
    ["fuzz_tooling_project_name"]="freerdp"
    ["duration"]=$delta_set_duration
)

declare -A libxml2_delta_2=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_base_ref"]="0f876b983249cd3fb32b53d405f5985e83d8c3bd"
    ["challenge_repo_head_ref"]="challenges/lx-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-delta-02"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$delta_set_duration
)

declare -A integration_test_delta_1=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/integration-test.git"
    ["challenge_repo_base_ref"]="4a714359c60858e3821bd478dc846de1d04dc977"
    ["challenge_repo_head_ref"]="challenges/integration-test-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/integration-test-delta-01"
    ["fuzz_tooling_project_name"]="integration-test"
    ["duration"]=$delta_set_duration
)

declare -A libpng_delta_1=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/example-libpng.git"
    ["challenge_repo_base_ref"]="5bf8da2d7953974e5dfbd778429c3affd461f51a"
    ["challenge_repo_head_ref"]="challenges/lp-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lp-delta-01"
    ["fuzz_tooling_project_name"]="libpng"
    ["duration"]=$delta_set_duration
)

declare -A sqlite_delta_1=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-sqlite3.git"
    ["challenge_repo_base_ref"]="6a3e7f57f00f0a2b6b89b0db7990e3df47175372"
    ["challenge_repo_head_ref"]="challenges/sq-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/sq-delta-01"
    ["fuzz_tooling_project_name"]="sqlite3"
    ["duration"]=$delta_set_duration
)

declare -A libxml2_delta_1=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_base_ref"]="39ce264d546f93a0ddb7a1d7987670b8b905c165"
    ["challenge_repo_head_ref"]="challenges/lx-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-delta-01"
    ["fuzz_tooling_project_name"]="libxml2"
    ["duration"]=$delta_set_duration
)

declare -A zookeeper_delta_1=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-zookeeper.git"
    ["challenge_repo_base_ref"]="f6f34f6d5b6d67205c34de617a0b99fe11e3d323"
    ["challenge_repo_head_ref"]="challenges/zk-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/zk-delta-01"
    ["fuzz_tooling_project_name"]="zookeeper"
    ["duration"]=$delta_set_duration
)

declare -A commons_compress_delta_2=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-commons-compress.git"
    ["challenge_repo_base_ref"]="154edd0066d1aaf18daafb88253cacbf39017d61"
    ["challenge_repo_head_ref"]="challenges/cc-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cc-delta-02"
    ["fuzz_tooling_project_name"]="apache-commons-compress"
    ["duration"]=$delta_set_duration
)

declare -A commons_compress_delta_3=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-commons-compress.git"
    ["challenge_repo_base_ref"]="6e608498013784abb6878cad7906c2ddc41e45f1"
    ["challenge_repo_head_ref"]="challenges/cc-delta-03"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cc-delta-03"
    ["fuzz_tooling_project_name"]="apache-commons-compress"
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
sim() {
    submit_task "freerdp_full"
    submit_task "libxml2_full"
    submit_task "sqlite_full"

    sleep $full_set_duration

    submit_task "commons_compress_full"
    submit_task "zookeeper_full"
    submit_task "dropbear_full"

    sleep $full_set_duration

    submit_task "freerdp_delta_1"
    submit_task "libxml2_delta_2"
    submit_task "integration_test_delta_1"
    submit_task "libpng_delta_1"

    sleep $delta_set_duration

    submit_task "sqlite_delta_1"
    submit_task "libxml2_delta_1"

    sleep $delta_set_duration

    submit_task "zookeeper_delta_1"
    submit_task "commons_compress_delta_2"
    submit_task "commons_compress_delta_3"

    sleep $delta_set_duration
}

all() {
    submit_task "commons_compress_full"
    submit_task "dropbear_full"
    submit_task "freerdp_full"
    submit_task "integration_test_delta_1"
    submit_task "libpng_delta_1"
    submit_task "libxml2_full"
    submit_task "sqlite_full"
    submit_task "zookeeper_full"
}

single() {
    submit_task "$1"
}

usage() {
    echo "Usage: $0 [sim|all|single <name>]"
    echo ""
    echo "sim           = Simulate round 2."
    echo "all           = Run one challenge from each repository."
    echo "single <name> = Run one challenge."
    echo ""
    echo "name = The name of the challenge to run:"
    echo "  commons_compress_full | commons_compress_delta_2 | commons_compress_delta_3"
    echo "  dropbear_full"
    echo "  freerdp_full | freerdp_delta_1"
    echo "  integration_test_delta_1"
    echo "  libpng_delta_1"
    echo "  libxml2_full | libxml2_delta_1 | libxml2_delta_2"
    echo "  sqlite_full | sqlite_delta_1"
    echo "  zookeeper_full | zookeeper_delta_1"
}

main() {
    if [ $# -eq 0 ]; then
        usage
        exit 1
    fi

    case "$1" in
        "sim")
            sim
            ;;
        "all")
            all
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
