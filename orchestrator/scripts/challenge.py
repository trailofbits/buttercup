#!/usr/bin/env python3

import argparse
import json
import subprocess
import time
import urllib.request
import sys
from typing import Any, Optional

SECONDS = 1
MINUTES = 60 * SECONDS
HOURS = 60 * MINUTES

FULL_SET_DURATION = 24 * HOURS
DELTA_SET_DURATION = 8 * HOURS

CHALLENGE_MAP = {
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

    print("\n", file=file)


def submit_task(task_name: str, **kwargs: Any) -> None:
    """Submit a task to the orchestrator."""
    if task_name not in CHALLENGE_MAP:
        print(f"Error: Unknown task '{task_name}'")
        return

    task_data = CHALLENGE_MAP[task_name].copy()

    for key, value in kwargs.items():
        task_data[key] = value

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

    submit_task("zk_ex1_delta_01", duration=delta_set_duration)
    submit_task("lx_ex1_delta_01", duration=delta_set_duration)

    time.sleep(delta_set_duration)


def sim2() -> None:
    """Simulate round 2."""
    full_set_duration = 24 * HOURS
    delta_set_duration = 8 * HOURS

    submit_task("fp_full_01", duration=full_set_duration)
    submit_task("lx_full_01", duration=full_set_duration)
    submit_task("sq_full_01", duration=full_set_duration)

    time.sleep(full_set_duration)

    submit_task("cc_full_01", duration=full_set_duration)
    submit_task("zk_full_01", duration=full_set_duration)
    submit_task("db_full_01", duration=full_set_duration)

    time.sleep(full_set_duration)

    submit_task("fp_delta_01", duration=delta_set_duration)
    submit_task("lx_delta_02", duration=delta_set_duration)
    submit_task("integration_test_delta_01", duration=delta_set_duration)
    submit_task("lp_delta_01", duration=delta_set_duration)

    time.sleep(delta_set_duration)

    submit_task("sq_delta_01", duration=delta_set_duration)
    submit_task("lx_delta_01", duration=delta_set_duration)

    time.sleep(delta_set_duration)

    submit_task("zk_delta_01", duration=delta_set_duration)
    submit_task("cc_delta_02", duration=delta_set_duration)
    submit_task("cc_delta_03", duration=delta_set_duration)

    time.sleep(delta_set_duration)


def sim3() -> None:
    """Simulate round 3."""
    full_set_duration = 12 * HOURS
    delta_set_duration = 6 * HOURS

    submit_task("fp_full_01", duration=full_set_duration)
    submit_task("sq_full_01", duration=full_set_duration)
    submit_task("db_full_01", duration=full_set_duration)
    submit_task("lo_full_01", duration=full_set_duration)
    submit_task("cu_full_01", duration=full_set_duration)

    time.sleep(full_set_duration)

    submit_task("cc_full_01", duration=full_set_duration)
    submit_task("zk_full_01", duration=full_set_duration)
    submit_task("tk_full_01", duration=full_set_duration)

    time.sleep(full_set_duration)

    submit_task("fp_delta_01", duration=delta_set_duration)
    submit_task("integration_test_delta_01", duration=delta_set_duration)
    submit_task("lp_delta_01", duration=delta_set_duration)
    submit_task("cu_delta_01", duration=delta_set_duration)
    submit_task("ex_delta_01", duration=delta_set_duration)

    time.sleep(delta_set_duration)

    submit_task("sq_delta_01", duration=delta_set_duration)
    submit_task("sq_delta_02", duration=delta_set_duration)
    submit_task("sq_delta_03", duration=delta_set_duration)
    submit_task("lx_delta_01", duration=delta_set_duration)
    submit_task("lx_delta_02", duration=delta_set_duration)

    time.sleep(delta_set_duration)

    submit_task("tk_delta_01", duration=delta_set_duration)
    submit_task("tk_delta_02", duration=delta_set_duration)
    submit_task("tk_delta_03", duration=delta_set_duration)
    submit_task("tk_delta_04", duration=delta_set_duration)
    submit_task("tk_delta_05", duration=delta_set_duration)

    time.sleep(delta_set_duration)

    submit_task("zk_delta_01", duration=delta_set_duration)
    submit_task("zk_delta_02", duration=delta_set_duration)
    submit_task("cc_delta_02", duration=delta_set_duration)
    submit_task("cc_delta_03", duration=delta_set_duration)

    time.sleep(delta_set_duration)

    submit_task("ipf_full_01", duration=full_set_duration)
    submit_task("s2n_full_01", duration=full_set_duration)

    time.sleep(full_set_duration)

    submit_task("integration_test_unharnessed_delta_01", duration=delta_set_duration)

    time.sleep(delta_set_duration)


def all_challenges() -> None:
    """Run one challenge from each repository."""
    full_set_duration = 12 * HOURS
    delta_set_duration = 6 * HOURS

    submit_task("cc_full_01", duration=full_set_duration)
    submit_task("cu_full_01", duration=full_set_duration)
    submit_task("db_full_01", duration=full_set_duration)
    submit_task("ex_delta_01", duration=delta_set_duration)
    submit_task("fp_full_01", duration=full_set_duration)
    submit_task("integration_test_delta_01", duration=delta_set_duration)
    submit_task("ipf_full_01", duration=full_set_duration)
    submit_task("lo_full_01", duration=full_set_duration)
    submit_task("lp_delta_01", duration=delta_set_duration)
    submit_task("lx_full_01", duration=full_set_duration)
    submit_task("s2n_full_01", duration=full_set_duration)
    submit_task("sq_full_01", duration=full_set_duration)
    submit_task("tk_full_01", duration=full_set_duration)
    submit_task("zk_full_01", duration=full_set_duration)


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
        submit_task(challenge_name, duration=duration)
        time.sleep(full_set_duration)


def single(challenge_name: str, duration: int) -> None:
    """Run one challenge for a given duration in seconds."""
    submit_task(challenge_name, duration=duration)
    time.sleep(duration)


def get_project_git_url_from_oss_fuzz(oss_fuzz_url: str, oss_fuzz_ref: str, project_name: str) -> Optional[str]:
    """Get project git URL from oss-fuzz project.yaml using grep."""
    try:
        # Create a temporary directory and clone/fetch the project.yaml
        cmd = [
            "bash", "-c", 
            f"git clone --depth 1 --branch {oss_fuzz_ref} {oss_fuzz_url} /tmp/oss-fuzz-temp 2>/dev/null && "
            f"grep -E '^main_repo:' /tmp/oss-fuzz-temp/projects/{project_name}/project.yaml | "
            f"sed 's/main_repo: *//g' | tr -d '\"'"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    finally:
        # Clean up
        subprocess.run(["rm", "-rf", "/tmp/oss-fuzz-temp"], capture_output=True)
    return None


def get_default_branch(repo_url: str) -> str:
    """Get the default branch name for a repository."""
    try:
        cmd = ["git", "ls-remote", "--symref", repo_url, "HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('ref: refs/heads/'):
                    branch_name = line.split('/')[-1].strip()
                    # Remove any trailing whitespace or tab characters
                    branch_name = branch_name.split()[0] if branch_name else "main"
                    return branch_name
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    return "main"


def yes_no_prompt(question: str, default: bool = True) -> bool:
    """Ask a yes/no question with a default answer."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{question} [{default_str}]: ").strip().lower()
        if response == "":
            return default
        elif response in ["y", "yes"]:
            return True
        elif response in ["n", "no"]:
            return False
        else:
            print("Please answer 'y' or 'n'")


def submit_project() -> None:
    """Interactive script to submit a custom challenge project."""
    print("=== Buttercup Custom Challenge Submission ===\n")
    
    task_data = {}
    
    # Question 1: OSS-Fuzz usage
    use_upstream_oss_fuzz = yes_no_prompt("Do you want to use upstream google/oss-fuzz?", True)
    
    if use_upstream_oss_fuzz:
        task_data["fuzz_tooling_url"] = "https://github.com/google/oss-fuzz"
        task_data["fuzz_tooling_ref"] = "master"
    else:
        custom_oss_fuzz_url = input("Enter custom oss-fuzz URL: ").strip()
        custom_oss_fuzz_ref = input("Enter custom oss-fuzz ref [master]: ").strip() or "master"
        task_data["fuzz_tooling_url"] = custom_oss_fuzz_url
        task_data["fuzz_tooling_ref"] = custom_oss_fuzz_ref
    
    # Question 2: OSS-Fuzz project name
    project_name = input("What's the oss-fuzz project name? ").strip()
    if not project_name:
        print("Error: Project name is required")
        return
    task_data["fuzz_tooling_project_name"] = project_name
    
    # Determine project URL from oss-fuzz
    print(f"\nLooking up project URL from oss-fuzz...")
    project_url = get_project_git_url_from_oss_fuzz(
        task_data["fuzz_tooling_url"], 
        task_data["fuzz_tooling_ref"], 
        project_name
    )
    
    # Question 3: Confirm or provide project URL
    if project_url:
        print(f"Determined project URL: {project_url}")
        if not yes_no_prompt("Is this URL correct?", True):
            project_url = input("Please provide the correct project URL: ").strip()
    else:
        print("Could not determine project URL from oss-fuzz")
        project_url = input("Please provide the project URL: ").strip()
    
    if not project_url:
        print("Error: Project URL is required")
        return
    task_data["challenge_repo_url"] = project_url
    
    # Question 4: Specific branch/commit analysis
    analyze_specific = yes_no_prompt("Do you want to analyze a specific branch/commit?", False)
    
    if analyze_specific:
        branch_or_commit = input("Enter branch/commit (use '..' for diff mode, e.g., 'base..head'): ").strip()
        if not branch_or_commit:
            print("Error: Branch/commit is required")
            return
            
        if ".." in branch_or_commit:
            # Diff mode
            base_ref, head_ref = branch_or_commit.split("..", 1)
            task_data["challenge_repo_base_ref"] = base_ref.strip()
            task_data["challenge_repo_head_ref"] = head_ref.strip()
            print(f"Using diff mode: {base_ref} -> {head_ref}")
        else:
            # Full mode
            task_data["challenge_repo_head_ref"] = branch_or_commit
            print(f"Using full mode: analyzing {branch_or_commit}")
    else:
        # Use default branch
        default_branch = get_default_branch(project_url)
        task_data["challenge_repo_head_ref"] = default_branch
        print(f"Using default branch: {default_branch}")
    
    # Question 5: Analysis duration
    while True:
        try:
            duration_minutes = input("How long should the analysis last? (in minutes) [30]: ").strip()
            if not duration_minutes:
                duration_minutes = "30"
            duration_seconds = int(duration_minutes) * MINUTES
            task_data["duration"] = duration_seconds
            break
        except ValueError:
            print("Please enter a valid number of minutes")
    
    # Set default values
    task_data["harnesses_included"] = True
    
    # Display final configuration
    print("\n=== Final Configuration ===")
    print(json.dumps(task_data, indent=2))
    
    if not yes_no_prompt("\nSubmit this configuration?", True):
        print("Cancelled.")
        return
    
    # Submit the task
    try:
        url = "http://127.0.0.1:31323/webhook/trigger_task"
        json_bytes = json.dumps(task_data).encode("utf-8")
        
        req = urllib.request.Request(url, data=json_bytes, headers={"Content-Type": "application/json"})
        print("\n=== Submitting Request ===")
        print_request(req)
        
        with urllib.request.urlopen(req) as response:
            response_data = response.read().decode("utf-8")
            print(f"Response status: {response.status}")
            if response.status == 200:
                print("✓ Task submitted successfully!")
            else:
                print(f"✗ Error response: {response_data}")
                
    except Exception as e:
        print(f"✗ Error submitting task: {e}")


def main() -> None:
    """Main function."""
    epilog_text = """
name = The name of the challenge to run:
  cc_full_01 | cc_delta_02 | cc_delta_03
  cu_full_01 | cu_delta_01
  db_full_01
  ex_delta_01
  fp_full_01 | fp_delta_01
  integration_test_delta_01 | integration_test_unharnessed_delta_01
  ipf_full_01
  lo_full_01
  lp_delta_01
  lx_full_01 | lx_delta_01 | lx_ex1_delta_01 | lx_delta_02
  s2n_full_01
  sq_full_01 | sq_delta_01 | sq_delta_02 | sq_delta_03
  tk_full_01 | tk_delta_01 | tk_delta_02 | tk_delta_03 | tk_delta_04 | tk_delta_05
  zk_full_01 | zk_delta_01 | zk_ex1_delta_01 | zk_delta_02

  lx_full_updated -> using the most recent version of helper.py
"""

    parser = argparse.ArgumentParser(
        description="Challenge submission utility",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    sim1_parser = subparsers.add_parser("sim1", help="Simulate round 1")
    sim1_parser.set_defaults(func=lambda args: sim1())

    sim2_parser = subparsers.add_parser("sim2", help="Simulate round 2")
    sim2_parser.set_defaults(func=lambda args: sim2())

    sim3_parser = subparsers.add_parser("sim3", help="Simulate round 3")
    sim3_parser.set_defaults(func=lambda args: sim3())

    all_parser = subparsers.add_parser("all", help="Run one challenge from each repository")
    all_parser.set_defaults(func=lambda args: all_challenges())

    testing_parser = subparsers.add_parser("testing", help="Run all challenges briefly for testing")
    testing_parser.set_defaults(func=lambda args: testing())

    single_parser = subparsers.add_parser("single", help="Run one challenge")
    single_parser.add_argument("name", type=str, choices=list(CHALLENGE_MAP.keys()), help="Challenge name")
    single_parser.add_argument("duration", type=int, help="Duration in seconds")
    single_parser.set_defaults(func=lambda args: single(args.name, args.duration))

    submit_project_parser = subparsers.add_parser("submit-project", help="Interactive submission of custom challenge project")
    submit_project_parser.set_defaults(func=lambda args: submit_project())

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
