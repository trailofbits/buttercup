#!/usr/bin/env python3

import json
import time
import urllib.request
import sys
from typing import Any

SECONDS: int = 1
MINUTES: int = 60 * SECONDS
HOURS: int = 60 * MINUTES

FULL_SET_DURATION: int = 24 * HOURS
DELTA_SET_DURATION: int = 8 * HOURS

CHALLENGE_MAP: dict[str, dict[str, Any]] = {
    "cc_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-commons-compress.git",
        "challenge_repo_head_ref": "challenges/cc-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/cc-full-01",
        "fuzz_tooling_project_name": "apache-commons-compress",
        "duration": FULL_SET_DURATION,
    },
    "cc_delta_02": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-commons-compress.git",
        "challenge_repo_base_ref": "154edd0066d1aaf18daafb88253cacbf39017d61",
        "challenge_repo_head_ref": "challenges/cc-delta-02",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/cc-delta-02",
        "fuzz_tooling_project_name": "apache-commons-compress",
        "duration": DELTA_SET_DURATION,
    },
    "cc_delta_03": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-commons-compress.git",
        "challenge_repo_base_ref": "6e608498013784abb6878cad7906c2ddc41e45f1",
        "challenge_repo_head_ref": "challenges/cc-delta-03",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/cc-delta-03",
        "fuzz_tooling_project_name": "apache-commons-compress",
        "duration": DELTA_SET_DURATION,
    },
    "cu_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-curl.git",
        "challenge_repo_head_ref": "challenges/cu-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/cu-full-01",
        "fuzz_tooling_project_name": "curl",
        "duration": FULL_SET_DURATION,
    },
    "cu_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-curl.git",
        "challenge_repo_base_ref": "a29184fc5f9b1474c08502d1545cd90375fadd51",
        "challenge_repo_head_ref": "challenges/cu-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/cu-delta-01",
        "fuzz_tooling_project_name": "curl",
        "duration": DELTA_SET_DURATION,
    },
    "db_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-dropbear.git",
        "challenge_repo_head_ref": "challenges/db-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/db-full-01",
        "fuzz_tooling_project_name": "dropbear",
        "duration": FULL_SET_DURATION,
    },
    "ex_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libexif.git",
        "challenge_repo_base_ref": "ffcdfbeb5539c25b1630ba59abf8a22587657adc",
        "challenge_repo_head_ref": "challenges/ex-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/ex-delta-01",
        "fuzz_tooling_project_name": "libexif",
        "duration": DELTA_SET_DURATION,
    },
    "fp_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-freerdp.git",
        "challenge_repo_head_ref": "challenges/fp-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/fp-full-01",
        "fuzz_tooling_project_name": "freerdp",
        "duration": FULL_SET_DURATION,
    },
    "fp_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-freerdp.git",
        "challenge_repo_base_ref": "a92cc0f3ebc3d3f4cf5b6097920a391e9b5fcfcf",
        "challenge_repo_head_ref": "challenges/fp-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/fp-delta-01",
        "fuzz_tooling_project_name": "freerdp",
        "duration": DELTA_SET_DURATION,
    },
    "integration_test_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/integration-test.git",
        "challenge_repo_base_ref": "4a714359c60858e3821bd478dc846de1d04dc977",
        "challenge_repo_head_ref": "challenges/integration-test-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "feature/macos-apple-silicon-support",
        "fuzz_tooling_project_name": "integration-test",
        "duration": DELTA_SET_DURATION,
    },
    "integration_test_unharnessed_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/integration-test.git",
        "challenge_repo_base_ref": "4a714359c60858e3821bd478dc846de1d04dc977",
        "challenge_repo_head_ref": "challenges/integration-test-unharnessed-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/integration-test-unharnessed-delta-01",
        "fuzz_tooling_project_name": "integration-test",
        "duration": DELTA_SET_DURATION,
        "harnesses_included": False,
    },
    "ipf_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-ipf.git",
        "challenge_repo_head_ref": "challenges/ipf-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/ipf-full-01",
        "fuzz_tooling_project_name": "ipf",
        "duration": FULL_SET_DURATION,
        "harnesses_included": False,
    },
    "lo_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libpostal.git",
        "challenge_repo_head_ref": "challenges/libpostal-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/libpostal-full-01",
        "fuzz_tooling_project_name": "libpostal",
        "duration": FULL_SET_DURATION,
    },
    "lp_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/example-libpng.git",
        "challenge_repo_base_ref": "5bf8da2d7953974e5dfbd778429c3affd461f51a",
        "challenge_repo_head_ref": "challenges/lp-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/lp-delta-01",
        "fuzz_tooling_project_name": "libpng",
        "duration": DELTA_SET_DURATION,
    },
    "lx_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libxml2.git",
        "challenge_repo_head_ref": "challenges/lx-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/lx-full-01",
        "fuzz_tooling_project_name": "libxml2",
        "duration": FULL_SET_DURATION,
    },
    "lx_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libxml2.git",
        "challenge_repo_base_ref": "39ce264d546f93a0ddb7a1d7987670b8b905c165",
        "challenge_repo_head_ref": "challenges/lx-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/lx-delta-01",
        "fuzz_tooling_project_name": "libxml2",
        "duration": DELTA_SET_DURATION,
    },
    "lx_ex1_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libxml2.git",
        "challenge_repo_base_ref": "792cc4a1462d4a969d9d38bd80a52d2e4f7bd137",
        "challenge_repo_head_ref": "9d1cb67c31933ee5ae3ee458940f7dbeb2fde8b8",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/lx-ex1-delta-01",
        "fuzz_tooling_project_name": "libxml2",
        "duration": DELTA_SET_DURATION,
    },
    "lx_delta_02": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libxml2.git",
        "challenge_repo_base_ref": "0f876b983249cd3fb32b53d405f5985e83d8c3bd",
        "challenge_repo_head_ref": "challenges/lx-delta-02",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/lx-delta-02",
        "fuzz_tooling_project_name": "libxml2",
        "duration": DELTA_SET_DURATION,
    },
    "lx_full_updated": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-libxml2.git",
        "challenge_repo_head_ref": "challenges/lx-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "aixcc-afc",
        "fuzz_tooling_project_name": "libxml2",
        "duration": FULL_SET_DURATION,
    },
    "s2n_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-s2n-tls.git",
        "challenge_repo_head_ref": "challenges/s2n-tls-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/s2n_tls-full-01",
        "fuzz_tooling_project_name": "s2n-tls",
        "duration": FULL_SET_DURATION,
        "harnesses_included": False,
    },
    "sq_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-sqlite3.git",
        "challenge_repo_head_ref": "challenges/sq-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/sq-full-01",
        "fuzz_tooling_project_name": "sqlite3",
        "duration": FULL_SET_DURATION,
    },
    "sq_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-sqlite3.git",
        "challenge_repo_base_ref": "6a3e7f57f00f0a2b6b89b0db7990e3df47175372",
        "challenge_repo_head_ref": "challenges/sq-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/sq-delta-01",
        "fuzz_tooling_project_name": "sqlite3",
        "duration": DELTA_SET_DURATION,
    },
    "sq_delta_02": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-sqlite3.git",
        "challenge_repo_base_ref": "d6a2180510e6fb05277f8325f132605399528505",
        "challenge_repo_head_ref": "challenges/sq-delta-02",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/sq-delta-02",
        "fuzz_tooling_project_name": "sqlite3",
        "duration": DELTA_SET_DURATION,
    },
    "sq_delta_03": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-sqlite3.git",
        "challenge_repo_base_ref": "35af1ffb5dd21ae47332577c2b6c889da302b497",
        "challenge_repo_head_ref": "challenges/sq-delta-03",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/sq-delta-03",
        "fuzz_tooling_project_name": "sqlite3",
        "duration": DELTA_SET_DURATION,
    },
    "tk_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-tika.git",
        "challenge_repo_head_ref": "challenges/tk-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/tk-full-01",
        "fuzz_tooling_project_name": "tika",
        "duration": FULL_SET_DURATION,
    },
    "tk_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-tika.git",
        "challenge_repo_base_ref": "d0e3069a8e51554083c2980974f869337b4d6d39",
        "challenge_repo_head_ref": "challenges/tk-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/tk-delta-01",
        "fuzz_tooling_project_name": "tika",
        "duration": DELTA_SET_DURATION,
    },
    "tk_delta_02": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-tika.git",
        "challenge_repo_base_ref": "87c62bccc3a6fd0343df073511fc520a235618b3",
        "challenge_repo_head_ref": "challenges/tk-delta-02",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/tk-delta-02",
        "fuzz_tooling_project_name": "tika",
        "duration": DELTA_SET_DURATION,
    },
    "tk_delta_03": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-tika.git",
        "challenge_repo_base_ref": "08dabf212d551b27de70d3be0653a226e85b1b73",
        "challenge_repo_head_ref": "challenges/tk-delta-03",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/tk-delta-03",
        "fuzz_tooling_project_name": "tika",
        "duration": DELTA_SET_DURATION,
    },
    "tk_delta_04": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-tika.git",
        "challenge_repo_base_ref": "30284a3eb45eddd5b812eca12254a99551671f32",
        "challenge_repo_head_ref": "challenges/tk-delta-04",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/tk-delta-04",
        "fuzz_tooling_project_name": "tika",
        "duration": DELTA_SET_DURATION,
    },
    "tk_delta_05": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-tika.git",
        "challenge_repo_base_ref": "4d5194b7d13494f97b89c859282342f5efad9cef",
        "challenge_repo_head_ref": "challenges/tk-delta-05",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/tk-delta-05",
        "fuzz_tooling_project_name": "tika",
        "duration": DELTA_SET_DURATION,
    },
    "zk_full_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-zookeeper.git",
        "challenge_repo_head_ref": "challenges/zk-full-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/zk-full-01",
        "fuzz_tooling_project_name": "zookeeper",
        "duration": FULL_SET_DURATION,
    },
    "zk_ex1_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-zookeeper.git",
        "challenge_repo_base_ref": "d19cef9ca254a4c1461490ed8b82ffccfa57461d",
        "challenge_repo_head_ref": "5ee4f185d0431cc88f365ce779aa04a87fe7690f",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/zk-ex1-delta-01",
        "fuzz_tooling_project_name": "zookeeper",
        "duration": DELTA_SET_DURATION,
    },
    "zk_delta_01": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-zookeeper.git",
        "challenge_repo_base_ref": "f6f34f6d5b6d67205c34de617a0b99fe11e3d323",
        "challenge_repo_head_ref": "challenges/zk-delta-01",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/zk-delta-01",
        "fuzz_tooling_project_name": "zookeeper",
        "duration": DELTA_SET_DURATION,
    },
    "zk_delta_02": {
        "challenge_repo_url": "https://github.com/tob-challenges/afc-zookeeper.git",
        "challenge_repo_base_ref": "7f350901823080c5dfa176b37c3f56f121dcd718",
        "challenge_repo_head_ref": "challenges/zk-delta-02",
        "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
        "fuzz_tooling_ref": "challenge-state/zk-delta-02",
        "fuzz_tooling_project_name": "zookeeper",
        "duration": DELTA_SET_DURATION,
    },
}


def print_request(req, file=sys.stderr):
    """Print a request object."""

    print(f"{req.get_method()} {req.full_url}", file=file)

    headers = dict(req.headers)
    max_key_len = max(len(k) for k in headers.keys()) if headers else 0
    for key, value in headers.items():
        print(f"{key.ljust(max_key_len)}: {value}", file=file)

    if req.data:
        if isinstance(req.data, bytes):
            try:
                data_str = req.data.decode("utf-8")
                data_json = json.loads(data_str)
                print(json.dumps(data_json, indent=2), file=file)

            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"{req.data}", file=file)
        else:
            print(f"{req.data}", file=file)

    print("\n")


def submit_task(task_name: str, overrides: list[tuple[str, Any]] = []) -> None:
    """Submit a task to the orchestrator."""
    if task_name not in CHALLENGE_MAP:
        print(f"Error: Unknown task '{task_name}'")
        return

    task_data = CHALLENGE_MAP[task_name].copy()

    for override in overrides:
        task_data[override[0]] = override[1]

    try:
        url = "http://localhost:31323/webhook/trigger_task"
        json_bytes = json.dumps(task_data).encode("utf-8")

        req = urllib.request.Request(url, data=json_bytes, headers={"Content-Type": "application/json"})
        print_request(req)

        with urllib.request.urlopen(req) as response:
            response_data = response.read().decode("utf-8")
            print(f"Response status: {response.status}")
            if response.status != 200:
                print(f"Response text: {response_data}")

    except Exception as e:
        print(f"Error submitting task: {e}")


def sim1() -> None:
    """Simulate round 1."""
    delta_set_duration = 48 * HOURS

    submit_task("zk_ex1_delta_01", [("duration", delta_set_duration)])
    submit_task("lx_ex1_delta_01", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)


def sim2() -> None:
    """Simulate round 2."""
    full_set_duration = 24 * HOURS
    delta_set_duration = 8 * HOURS

    submit_task("fp_full_01", [("duration", full_set_duration)])
    submit_task("lx_full_01", [("duration", full_set_duration)])
    submit_task("sq_full_01", [("duration", full_set_duration)])

    time.sleep(full_set_duration)

    submit_task("cc_full_01", [("duration", full_set_duration)])
    submit_task("zk_full_01", [("duration", full_set_duration)])
    submit_task("db_full_01", [("duration", full_set_duration)])

    time.sleep(full_set_duration)

    submit_task("fp_delta_01", [("duration", delta_set_duration)])
    submit_task("lx_delta_02", [("duration", delta_set_duration)])
    submit_task("integration_test_delta_01", [("duration", delta_set_duration)])
    submit_task("lp_delta_01", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)

    submit_task("sq_delta_01", [("duration", delta_set_duration)])
    submit_task("lx_delta_01", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)

    submit_task("zk_delta_01", [("duration", delta_set_duration)])
    submit_task("cc_delta_02", [("duration", delta_set_duration)])
    submit_task("cc_delta_03", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)


def sim3() -> None:
    """Simulate round 3."""
    full_set_duration = 12 * HOURS
    delta_set_duration = 6 * HOURS

    submit_task("fp_full_01", [("duration", full_set_duration)])
    submit_task("sq_full_01", [("duration", full_set_duration)])
    submit_task("db_full_01", [("duration", full_set_duration)])
    submit_task("lo_full_01", [("duration", full_set_duration)])
    submit_task("cu_full_01", [("duration", full_set_duration)])

    time.sleep(full_set_duration)

    submit_task("cc_full_01", [("duration", full_set_duration)])
    submit_task("zk_full_01", [("duration", full_set_duration)])
    submit_task("tk_full_01", [("duration", full_set_duration)])

    time.sleep(full_set_duration)

    submit_task("fp_delta_01", [("duration", delta_set_duration)])
    submit_task("integration_test_delta_01", [("duration", delta_set_duration)])
    submit_task("lp_delta_01", [("duration", delta_set_duration)])
    submit_task("cu_delta_01", [("duration", delta_set_duration)])
    submit_task("ex_delta_01", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)

    submit_task("sq_delta_01", [("duration", delta_set_duration)])
    submit_task("sq_delta_02", [("duration", delta_set_duration)])
    submit_task("sq_delta_03", [("duration", delta_set_duration)])
    submit_task("lx_delta_01", [("duration", delta_set_duration)])
    submit_task("lx_delta_02", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)

    submit_task("tk_delta_01", [("duration", delta_set_duration)])
    submit_task("tk_delta_02", [("duration", delta_set_duration)])
    submit_task("tk_delta_03", [("duration", delta_set_duration)])
    submit_task("tk_delta_04", [("duration", delta_set_duration)])
    submit_task("tk_delta_05", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)

    submit_task("zk_delta_01", [("duration", delta_set_duration)])
    submit_task("zk_delta_02", [("duration", delta_set_duration)])
    submit_task("cc_delta_02", [("duration", delta_set_duration)])
    submit_task("cc_delta_03", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)

    submit_task("ipf_full_01", [("duration", full_set_duration)])
    submit_task("s2n_full_01", [("duration", full_set_duration)])

    time.sleep(full_set_duration)

    submit_task("integration_test_unharnessed_delta_01", [("duration", delta_set_duration)])

    time.sleep(delta_set_duration)


def all_challenges() -> None:
    """Run one challenge from each repository."""
    full_set_duration = 12 * HOURS
    delta_set_duration = 6 * HOURS

    submit_task("cc_full_01", [("duration", full_set_duration)])
    submit_task("cu_full_01", [("duration", full_set_duration)])
    submit_task("db_full_01", [("duration", full_set_duration)])
    submit_task("ex_delta_01", [("duration", delta_set_duration)])
    submit_task("fp_full_01", [("duration", full_set_duration)])
    submit_task("integration_test_delta_01", [("duration", delta_set_duration)])
    submit_task("ipf_full_01", [("duration", full_set_duration)])
    submit_task("lo_full_01", [("duration", full_set_duration)])
    submit_task("lp_delta_01", [("duration", delta_set_duration)])
    submit_task("lx_full_01", [("duration", full_set_duration)])
    submit_task("s2n_full_01", [("duration", full_set_duration)])
    submit_task("sq_full_01", [("duration", full_set_duration)])
    submit_task("tk_full_01", [("duration", full_set_duration)])
    submit_task("zk_full_01", [("duration", full_set_duration)])


def testing() -> None:
    """Run all challenges briefly for testing."""
    full_set_duration = 1 * MINUTES
    delta_set_duration = 1 * MINUTES

    challenges = [
        ("cc_full_01", full_set_duration),
        ("cc_delta_02", delta_set_duration),
        ("cc_delta_03", delta_set_duration),
        ("cu_full_01", full_set_duration),
        ("cu_delta_01", delta_set_duration),
        ("db_full_01", full_set_duration),
        ("ex_delta_01", delta_set_duration),
        ("fp_full_01", full_set_duration),
        ("fp_delta_01", delta_set_duration),
        ("integration_test_delta_01", delta_set_duration),
        ("integration_test_unharnessed_delta_01", delta_set_duration),
        ("ipf_full_01", full_set_duration),
        ("lo_full_01", full_set_duration),
        ("lp_delta_01", delta_set_duration),
        ("lx_full_01", full_set_duration),
        ("lx_delta_01", delta_set_duration),
        ("lx_ex1_delta_01", delta_set_duration),
        ("lx_delta_02", delta_set_duration),
        ("lx_full_updated", full_set_duration),
        ("s2n_full_01", full_set_duration),
        ("sq_full_01", full_set_duration),
        ("sq_delta_01", delta_set_duration),
        ("sq_delta_02", delta_set_duration),
        ("sq_delta_03", delta_set_duration),
        ("tk_full_01", full_set_duration),
        ("tk_delta_01", delta_set_duration),
        ("tk_delta_02", delta_set_duration),
        ("tk_delta_03", delta_set_duration),
        ("tk_delta_04", delta_set_duration),
        ("tk_delta_05", delta_set_duration),
        ("zk_full_01", full_set_duration),
        ("zk_ex1_delta_01", delta_set_duration),
        ("zk_delta_01", delta_set_duration),
        ("zk_delta_02", delta_set_duration),
    ]

    for challenge_name, duration in challenges:
        submit_task(challenge_name, [("duration", duration)])
        time.sleep(full_set_duration)


def single(challenge_name: str, duration: int) -> None:
    """Run one challenge for a given duration in seconds."""
    submit_task(challenge_name, [("duration", duration)])
    time.sleep(duration)


def usage() -> None:
    """Print usage information."""
    print("Usage: python challenge.py [sim1|sim2|sim3|all|testing|single <name> <duration>]\n")

    print("sim1          = Simulate round 1.")
    print("sim2          = Simulate round 2.")
    print("sim3          = Simulate round 3.")
    print("all           = Run one challenge from each repository.")
    print("testing       = Run all challenges briefly for testing.")
    print("single <name> <duration> = Run one challenge for a given duration in seconds.\n")

    print("name = The name of the challenge to run:")
    print("\tcc_full_01 | cc_delta_02 | cc_delta_03")
    print("\tcu_full_01 | cu_delta_01")
    print("\tdb_full_01")
    print("\tex_delta_01")
    print("\tfp_full_01 | fp_delta_01")
    print("\tintegration_test_delta_01 | integration_test_unharnessed_delta_01")
    print("\tipf_full_01")
    print("\tlo_full_01")
    print("\tlp_delta_01")
    print("\tlx_full_01 | lx_delta_01 | lx_ex1_delta_01 | lx_delta_02")
    print("\ts2n_full_01")
    print("\tsq_full_01 | sq_delta_01 | sq_delta_02 | sq_delta_03")
    print("\ttk_full_01 | tk_delta_01 | tk_delta_02 | tk_delta_03 | tk_delta_04 | tk_delta_05")
    print("\tzk_full_01 | zk_delta_01 | zk_ex1_delta_01 | zk_delta_02\n")

    print("\tlx_full_updated -> using the most recent version of helper.py")


def main() -> None:
    """Main function."""
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "sim1":
        sim1()
    elif command == "sim2":
        sim2()
    elif command == "sim3":
        sim3()
    elif command == "all":
        all_challenges()
    elif command == "testing":
        testing()
    elif command == "single":
        if len(sys.argv) != 4:
            usage()
            sys.exit(1)
        challenge_name = sys.argv[2]
        try:
            duration = int(sys.argv[3])
        except ValueError:
            print("Error: duration must be an integer")
            sys.exit(1)
        single(challenge_name, duration)
    else:
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
