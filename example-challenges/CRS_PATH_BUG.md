# CRS Path Bug Report

## Summary

The Buttercup CRS has a bug in how it constructs the path to `infra/helper.py` when processing OSS-Fuzz projects, preventing successful task processing.

## Bug Details

### Location
- File: `common/src/buttercup/common/challenge_task.py`
- Method: `ChallengeTask.__post_init__()`

### Issue
The CRS incorrectly constructs the path to `infra/helper.py`:

1. `get_oss_fuzz_path()` returns the first directory inside `fuzz-tooling/` (e.g., `fuzz-tooling/infra`)
2. It then appends `infra/helper.py` to this path
3. This results in looking for `fuzz-tooling/infra/infra/helper.py` instead of `fuzz-tooling/infra/helper.py`

### Code Flow
```python
# In ChallengeTask.__post_init__
self._helper_path = Path("infra/helper.py")
oss_fuzz_path = self.get_oss_fuzz_path()  # Returns fuzz-tooling/infra
if not (oss_fuzz_path / self._helper_path).exists():  # Checks fuzz-tooling/infra/infra/helper.py
    raise ChallengeTaskError(f"Missing required file: {oss_fuzz_path / self._helper_path}")
```

### Root Cause
The `_find_first_dir()` method returns the first directory it finds in `fuzz-tooling/`, which is then used as the base path. This works if the first directory is the actual OSS-Fuzz root, but fails when there are multiple directories (like `infra` and project directories).

## Impact

- Tasks cannot be processed beyond the download stage
- Fuzzing never starts due to validation failure
- The submission script and file downloads work correctly

## Workaround Attempts

1. **Restructuring the project**: Tried various directory structures but the bug persists
2. **Adding duplicate paths**: Tried adding `infra/infra/helper.py` but this is not a clean solution

## Suggested Fix

The CRS should either:
1. Look for `helper.py` directly at `fuzz-tooling/infra/helper.py` without using `_find_first_dir()`
2. Or properly identify the OSS-Fuzz root directory instead of picking the first directory

## Test Results

Successfully implemented and tested:
- ✅ Challenge submission script with uvx/uv
- ✅ HTTP file server with download logging
- ✅ Task submission to CRS API
- ✅ File downloads by task-downloader
- ✅ Monitoring script for results
- ❌ Fuzzing execution (blocked by helper.py path bug)

## Example Error

```
scheduler-1  | 2025-07-16 01:54:09,560 - buttercup.orchestrator.scheduler.scheduler - ERROR - Failed to process task 62070e2f-9626-448e-a407-5b387da10be2: Missing required file: /node_data/tasks_storage/62070e2f-9626-448e-a407-5b387da10be2/fuzz-tooling/infra/infra/helper.py
```