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

declare -A cu_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-curl.git"
    ["challenge_repo_head_ref"]="challenges/cu-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cu-full-01"
    ["fuzz_tooling_project_name"]="curl"
    ["duration"]=$full_set_duration
)

declare -A cu_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-curl.git"
    ["challenge_repo_base_ref"]="a29184fc5f9b1474c08502d1545cd90375fadd51"
    ["challenge_repo_head_ref"]="challenges/cu-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/cu-delta-01"
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

declare -A ex_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libexif.git"
    ["challenge_repo_base_ref"]="ffcdfbeb5539c25b1630ba59abf8a22587657adc"
    ["challenge_repo_head_ref"]="challenges/ex-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/ex-delta-01"
    ["fuzz_tooling_project_name"]="libexif"
    ["duration"]=$delta_set_duration
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

declare -A integration_test_unharnessed_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/integration-test.git"
    ["challenge_repo_base_ref"]="4a714359c60858e3821bd478dc846de1d04dc977"
    ["challenge_repo_head_ref"]="challenges/integration-test-unharnessed-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/integration-test-unharnessed-delta-01"
    ["fuzz_tooling_project_name"]="integration-test"
    ["duration"]=$delta_set_duration
    ["harnesses_included"]=false
)

declare -A ipf_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-ipf.git"
    ["challenge_repo_head_ref"]="challenges/ipf-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/ipf-full-01"
    ["fuzz_tooling_project_name"]="ipf"
    ["duration"]=$full_set_duration
    ["harnesses_included"]=false
)

declare -A lo_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libpostal.git"
    ["challenge_repo_head_ref"]="challenges/libpostal-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/libpostal-full-01"
    ["fuzz_tooling_project_name"]="libpostal"
    ["duration"]=$full_set_duration
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

declare -A lx_ex1_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-libxml2.git"
    ["challenge_repo_base_ref"]="792cc4a1462d4a969d9d38bd80a52d2e4f7bd137"
    ["challenge_repo_head_ref"]="9d1cb67c31933ee5ae3ee458940f7dbeb2fde8b8"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/lx-ex1-delta-01"
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

declare -A s2n_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-s2n-tls.git"
    ["challenge_repo_head_ref"]="challenges/s2n-tls-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/s2n_tls-full-01"
    ["fuzz_tooling_project_name"]="s2n-tls"
    ["duration"]=$full_set_duration
    ["harnesses_included"]=false
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

declare -A sq_delta_02=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-sqlite3.git"
    ["challenge_repo_base_ref"]="d6a2180510e6fb05277f8325f132605399528505"
    ["challenge_repo_head_ref"]="challenges/sq-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/sq-delta-02"
    ["fuzz_tooling_project_name"]="sqlite3"
    ["duration"]=$delta_set_duration
)

declare -A sq_delta_03=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-sqlite3.git"
    ["challenge_repo_base_ref"]="35af1ffb5dd21ae47332577c2b6c889da302b497"
    ["challenge_repo_head_ref"]="challenges/sq-delta-03"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/sq-delta-03"
    ["fuzz_tooling_project_name"]="sqlite3"
    ["duration"]=$delta_set_duration
)

declare -A tk_full_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-tika.git"
    ["challenge_repo_head_ref"]="challenges/tk-full-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/tk-full-01"
    ["fuzz_tooling_project_name"]="tika"
    ["duration"]=$full_set_duration
)

declare -A tk_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-tika.git"
    ["challenge_repo_base_ref"]="d0e3069a8e51554083c2980974f869337b4d6d39"
    ["challenge_repo_head_ref"]="challenges/tk-delta-01"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/tk-delta-01"
    ["fuzz_tooling_project_name"]="tika"
    ["duration"]=$delta_set_duration
)

declare -A tk_delta_02=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-tika.git"
    ["challenge_repo_base_ref"]="87c62bccc3a6fd0343df073511fc520a235618b3"
    ["challenge_repo_head_ref"]="challenges/tk-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/tk-delta-02"
    ["fuzz_tooling_project_name"]="tika"
    ["duration"]=$delta_set_duration
)

declare -A tk_delta_03=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-tika.git"
    ["challenge_repo_base_ref"]="08dabf212d551b27de70d3be0653a226e85b1b73"
    ["challenge_repo_head_ref"]="challenges/tk-delta-03"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/tk-delta-03"
    ["fuzz_tooling_project_name"]="tika"
    ["duration"]=$delta_set_duration
)

declare -A tk_delta_04=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-tika.git"
    ["challenge_repo_base_ref"]="30284a3eb45eddd5b812eca12254a99551671f32"
    ["challenge_repo_head_ref"]="challenges/tk-delta-04"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/tk-delta-04"
    ["fuzz_tooling_project_name"]="tika"
    ["duration"]=$delta_set_duration
)

declare -A tk_delta_05=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-tika.git"
    ["challenge_repo_base_ref"]="4d5194b7d13494f97b89c859282342f5efad9cef"
    ["challenge_repo_head_ref"]="challenges/tk-delta-05"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/tk-delta-05"
    ["fuzz_tooling_project_name"]="tika"
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

declare -A zk_ex1_delta_01=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-zookeeper.git"
    ["challenge_repo_base_ref"]="d19cef9ca254a4c1461490ed8b82ffccfa57461d"
    ["challenge_repo_head_ref"]="5ee4f185d0431cc88f365ce779aa04a87fe7690f"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/zk-ex1-delta-01"
    ["fuzz_tooling_project_name"]="zookeeper"
    ["duration"]=$delta_set_duration
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

declare -A zk_delta_02=(
    ["challenge_repo_url"]="git@github.com:aixcc-finals/afc-zookeeper.git"
    ["challenge_repo_base_ref"]="7f350901823080c5dfa176b37c3f56f121dcd718"
    ["challenge_repo_head_ref"]="challenges/zk-delta-02"
    ["fuzz_tooling_url"]="git@github.com:aixcc-finals/oss-fuzz-aixcc.git"
    ["fuzz_tooling_ref"]="challenge-state/zk-delta-02"
    ["fuzz_tooling_project_name"]="zookeeper"
    ["duration"]=$delta_set_duration
)

submit_task() {
    task_name=$1
    key=$2
    value=$3
    declare -n task_data_ref=$task_name

    # Update the array if value is provided
    if [ ! -z "$value" ]; then
        task_data_ref[$key]=$value
    fi

    echo $task_name
    echo "${task_data_ref[@]}"

    # Convert associative array to JSON
    json_data="{"
    for key in "${!task_data_ref[@]}"; do
        value="${task_data_ref[$key]}"
        # Check if value is numeric (integer) or boolean
        if [[ "$value" =~ ^[0-9]+$ ]]; then
            json_data+="\"$key\":$value,"
        elif [[ "$value" == "true" || "$value" == "false" ]]; then
            json_data+="\"$key\":$value,"
        else
            json_data+="\"$key\":\"$value\","
        fi
    done
    json_data="${json_data%,}}"  # Remove trailing comma

    echo $json_data | jq -C '.'
    curl -X 'POST' 'http://127.0.0.1:31323/webhook/trigger_task' -H 'Content-Type: application/json' -d "$json_data"
}

# From: https://github.com/aixcc-finals/example-crs-architecture/blob/879eaa9a6d5b761ecfcf78d3bda9c0c612c0fac7/docs/round_info/exhibition-round-1.md
sim1() {
    delta_set_duration=$((48 * $hours))

    submit_task "zk_ex1_delta_01" "duration" $delta_set_duration
    submit_task "lx_ex1_delta_01" "duration" $delta_set_duration

    sleep $delta_set_duration
}

# From: https://github.com/aixcc-finals/example-crs-architecture/blob/1ccabc62b177a86a49c69a5d3b085eea299223ce/docs/round_info/exhibition-round-2.md#challenge-tasks-archive
sim2() {
    full_set_duration=$((24 * $hours))
    delta_set_duration=$((8 * $hours))

    submit_task "fp_full_01" "duration" $full_set_duration
    submit_task "lx_full_01" "duration" $full_set_duration
    submit_task "sq_full_01" "duration" $full_set_duration

    sleep $full_set_duration

    submit_task "cc_full_01" "duration" $full_set_duration
    submit_task "zk_full_01" "duration" $full_set_duration
    submit_task "db_full_01" "duration" $full_set_duration

    sleep $full_set_duration

    submit_task "fp_delta_01" "duration" $delta_set_duration
    submit_task "lx_delta_02" "duration" $delta_set_duration
    submit_task "integration_test_delta_01" "duration" $delta_set_duration
    submit_task "lp_delta_01" "duration" $delta_set_duration

    sleep $delta_set_duration

    submit_task "sq_delta_01" "duration" $delta_set_duration
    submit_task "lx_delta_01" "duration" $delta_set_duration

    sleep $delta_set_duration

    submit_task "zk_delta_01" "duration" $delta_set_duration
    submit_task "cc_delta_02" "duration" $delta_set_duration
    submit_task "cc_delta_03" "duration" $delta_set_duration

    sleep $delta_set_duration
}

# From: https://github.com/aixcc-finals/example-crs-architecture/blob/main/docs/round_info/exhibition-round-3.md
sim3() {
    full_set_duration=$((12 * $hours))
    delta_set_duration=$((6 * $hours))

    submit_task "fp_full_01" "duration" $full_set_duration
    submit_task "sq_full_01" "duration" $full_set_duration
    submit_task "db_full_01" "duration" $full_set_duration
    submit_task "lo_full_01" "duration" $full_set_duration
    submit_task "cu_full_01" "duration" $full_set_duration

    sleep $full_set_duration

    submit_task "cc_full_01" "duration" $full_set_duration
    submit_task "zk_full_01" "duration" $full_set_duration
    submit_task "tk_full_01" "duration" $full_set_duration

    sleep $full_set_duration

    submit_task "fp_delta_01" "duration" $delta_set_duration
    submit_task "integration_test_delta_01" "duration" $delta_set_duration
    submit_task "lp_delta_01" "duration" $delta_set_duration
    submit_task "cu_delta_01" "duration" $delta_set_duration
    submit_task "ex_delta_01" "duration" $delta_set_duration

    sleep $delta_set_duration

    submit_task "sq_delta_01" "duration" $delta_set_duration
    submit_task "sq_delta_02" "duration" $delta_set_duration
    submit_task "sq_delta_03" "duration" $delta_set_duration
    submit_task "lx_delta_01" "duration" $delta_set_duration
    submit_task "lx_delta_02" "duration" $delta_set_duration

    sleep $delta_set_duration

    submit_task "tk_delta_01" "duration" $delta_set_duration
    submit_task "tk_delta_02" "duration" $delta_set_duration
    submit_task "tk_delta_03" "duration" $delta_set_duration
    submit_task "tk_delta_04" "duration" $delta_set_duration
    submit_task "tk_delta_05" "duration" $delta_set_duration

    sleep $delta_set_duration

    submit_task "zk_delta_01" "duration" $delta_set_duration
    submit_task "zk_delta_02" "duration" $delta_set_duration
    submit_task "cc_delta_02" "duration" $delta_set_duration
    submit_task "cc_delta_03" "duration" $delta_set_duration

    sleep $delta_set_duration

    submit_task "ipf_full_01" "duration" $full_set_duration
    submit_task "s2n_full_01" "duration" $full_set_duration

    sleep $full_set_duration

    submit_task "integration_test_unharnessed_delta_01" "duration" $delta_set_duration

    sleep $delta_set_duration
}

all() {
    full_set_duration=$((12 * $hours))
    delta_set_duration=$((6 * $hours))

    submit_task "cc_full_01" "duration" $full_set_duration
    submit_task "cu_full_01" "duration" $full_set_duration
    submit_task "db_full_01" "duration" $full_set_duration
    submit_task "ex_delta_01" "duration" $delta_set_duration
    submit_task "fp_full_01" "duration" $full_set_duration
    submit_task "integration_test_delta_01" "duration" $delta_set_duration
    submit_task "ipf_full_01" "duration" $full_set_duration
    submit_task "lo_full_01" "duration" $full_set_duration
    submit_task "lp_delta_01" "duration" $delta_set_duration
    submit_task "lx_full_01" "duration" $full_set_duration
    submit_task "s2n_full_01" "duration" $full_set_duration
    submit_task "sq_full_01" "duration" $full_set_duration
    submit_task "tk_full_01" "duration" $full_set_duration
    submit_task "zk_full_01" "duration" $full_set_duration
}

# Check if the tasks are being processed:
# $ kubectl logs -n crs -l app=scheduler --tail=-1 | grep "Processing task" | cut -d' ' -f10- | sort | uniq"
# Check if tasks have been built:
# $ kubectl logs -n crs -l app=scheduler --tail=-1 | grep "Acked build output" | cut -d' ' -f11 | sort | uniq
# Check which sanitizers have been built:
# $ kubectl logs -n crs -l app=scheduler --tail=-1 | grep "Acked build output" | cut -d' ' -f11-16

testing() {
    full_set_duration=$((1 * $minutes))
    delta_set_duration=$((1 * $minutes))

    submit_task "cc_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "cc_delta_02" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "cc_delta_03" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "cu_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "cu_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "db_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "ex_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "fp_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "fp_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "integration_test_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "integration_test_unharnessed_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "ipf_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "lo_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "lp_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "lx_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "lx_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "lx_ex1_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "lx_delta_02" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "lx_full_updated" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "s2n_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "sq_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "sq_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "sq_delta_02" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "sq_delta_03" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "tk_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "tk_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "tk_delta_02" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "tk_delta_03" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "tk_delta_04" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "tk_delta_05" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "zk_full_01" "duration" $full_set_duration
    sleep $full_set_duration
    submit_task "zk_ex1_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "zk_delta_01" "duration" $delta_set_duration
    sleep $full_set_duration
    submit_task "zk_delta_02" "duration" $delta_set_duration
    sleep $full_set_duration
}

single() {
    submit_task "$1"
}

usage() {
    echo "Usage: $0 [sim1|sim2|sim3|all|testing|single <name>]"
    echo ""
    echo "sim1          = Simulate round 1."
    echo "sim2          = Simulate round 2."
    echo "sim3          = Simulate round 3."
    echo "all           = Run one challenge from each repository."
    echo "testing       = Run all challenges briefly for testing."
    echo "single <name> = Run one challenge."
    echo ""
    echo "name = The name of the challenge to run:"
    echo "  cc_full_01 | cc_delta_02 | cc_delta_03"
    echo "  cu_full_01 | cu_delta_01"
    echo "  db_full_01"
    echo "  ex_delta_01"
    echo "  fp_full_01 | fp_delta_01"
    echo "  integration_test_delta_01 | integration_test_unharnessed_delta_01"
    echo "  ipf_full_01"
    echo "  lo_full_01"
    echo "  lp_delta_01"
    echo "  lx_full_01 | lx_delta_01 | lx_ex1_delta_01 | lx_delta_02"
    echo "  s2n_full_01"
    echo "  sq_full_01 | sq_delta_01 | sq_delta_02 | sq_delta_03"
    echo "  tk_full_01 | tk_delta_01 | tk_delta_02 | tk_delta_03 | tk_delta_04 | tk_delta_05"
    echo "  zk_full_01 | zk_delta_01 | zk_ex1_delta_01 | zk_delta_02"
    echo ""
    echo "  lx_full_updated -> using the most recent version of helper.py"
}

main() {
    if [ $# -eq 0 ]; then
        usage
        exit 1
    fi

    case "$1" in
        "sim1")
            sim1
            ;;
        "sim2")
            sim2
            ;;
        "sim3")
            sim3
            ;;
        "all")
            all
            ;;
        "testing")
            testing
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
