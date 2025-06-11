# Unscored

This document serves as instructions on running each challenge from the unscored rounds.

We want to verify that our CRS **still** finds vulnerabilities and patches we have ground-truth for.
Consider this an extra validation apart from our unit and regression tests.

A list of vulnerabilities to find and patch is in this [spreadsheet](https://docs.google.com/spreadsheets/d/1y9Bj0ficMp6VvVz6bCgqYZPqv36l0Yhvxs0D_xuKgDY/edit).

## Setup

* Set up minikube locally on your machine (see [README.md](README.md)).

* `cd deployment && make up`

* Wait for all components to be `Running`: `watch 'kubectl get pods -n crs'`

* `kubectl port-forward -n crs service/buttercup-competition-api 31323:1323`

## Steps

* Run CRS on a challenge: `./orchestrator/scripts/challenge.sh`

* Validate Vulnerabilities and Patches
  * We found the correct vulnerability if the ground-truth patch fixes the vulnerability.
  * We found the correct patch if the ground-truth vulnerability gets fixed by the patch.

* Put the PoV blobs and Patch files into this [folder](https://drive.google.com/drive/folders/1nkOVqQJc1u15VFTboquax1CH_98RQGnS).

## Example

### Validate the correct Vulnerability and Patch

```shell
git clone git@github.com:aixcc-finals/example-libpng.git
cd example-libpng/
git checkout challenges/lp-delta-01
cd ../

git clone git@github.com:aixcc-finals/oss-fuzz-aixcc.git
cd oss-fuzz-aixcc/
git checkout challenge-state/lp-delta-01

# Build fuzzers
python3 infra/helper.py build_image --pull libpng
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/
python3 infra/helper.py check_build --sanitizer address --engine libfuzzer libpng

# Observe crash
python3 infra/helper.py reproduce libpng libpng_read_fuzzer ../example-libpng/.aixcc/vulns/vuln_0/blobs/data.bin

# Rebuild with patch
cd ../example-libpng/
patch < .aixcc/vulns/vuln_0/patches/good_patch_1.diff
cd ../oss-fuzz-aixcc/
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/

# Observe that crash is prevented
python3 infra/helper.py reproduce libpng libpng_read_fuzzer ../example-libpng/.aixcc/vulns/vuln_0/blobs/data.bin

# Reset challenge
cd ../example-libpng/
git reset --hard HEAD
cd ../oss-fuzz-aixcc/
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/
```

### Submit challenge

* `./orchestrator/scripts/challenge.sh single lp_delta_01`

* `kubectl port-forward -n crs service/buttercup-redis-master 16379:6379`

* Access `redis` server

  * `cd common/`
    * Note: need to run `uv venv` the first time and `uv sync` after changes have been made.
  * `source .venv/bin/activate`
  * `buttercup-util --help`

  * `buttercup-util --redis_url redis://localhost:16379 list_queues`
  * `buttercup-util --redis_url redis://localhost:16379 read_queue tasks_ready_queue`

### Check if we found a Vulnerability and Patch

* Check for crashes: `buttercup-util --redis_url redis://localhost:16379 read_queue confirmed_vulnerabilities_queue`

* Copy crash input file:
  * `buttercup-util --redis_url redis://localhost:16379 read_queue confirmed_vulnerabilities_queue | grep "crash_input_path"`
  * `kubectl get pods -n crs | grep fuzzer`
  * `kubectl cp crs/<fuzzer-bot-name>:<crash-path> crash`

* Check for patches: `buttercup-util --redis_url redis://localhost:16379 read_queue patches_queue`

* Copy patch file:
  * `buttercup-util --redis_url redis://localhost:16379 read_queue patches_queue | grep "patch:" > patch.diff`
  * Modify `patch.diff`. In vim: `:%s/\\n/\r/g`

### Validate our Vulernability and Patch

```shell
cd oss-fuzz-aixcc/

# Observe your crash
python3 infra/helper.py reproduce libpng libpng_read_fuzzer ../common/crash

# Rebuild with correct patch
cd ../example-libpng/
patch < .aixcc/vulns/vuln_0/patches/good_patch_1.diff
cd ../oss-fuzz-aixcc/
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/

# Observe if your crash is prevented
python3 infra/helper.py reproduce libpng libpng_read_fuzzer ../common/crash

# Reset challenge
cd ../example-libpng/
git reset --hard HEAD
cd ../oss-fuzz-aixcc/
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/


# Observe the correct crash
python3 infra/helper.py reproduce libpng libpng_read_fuzzer ../example-libpng/.aixcc/vulns/vuln_0/blobs/data.bin

# Rebuild with your patch
cd ../example-libpng/
patch < ../common/patch.diff
cd ../oss-fuzz-aixcc/
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/

# Observe if the correct crash is prevented
python3 infra/helper.py reproduce libpng libpng_read_fuzzer ../example-libpng/.aixcc/vulns/vuln_0/blobs/data.bin

# Reset challenge
cd ../example-libpng/
git reset --hard HEAD
cd ../oss-fuzz-aixcc/
python3 infra/helper.py build_fuzzers --clean --sanitizer address --engine libfuzzer libpng ../example-libpng/
```

### Upload our Vulnerability and Patch files to drive folder for future reference (above).
