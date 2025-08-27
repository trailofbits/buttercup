# Scored

This document describes how to parse logs from the final round of the AIxCC competition.

**NOTE**: PoVs were not released to us immediately because DARPA is still involved in responsible disclosure: <https://aicyberchallenge.com/Finals-winners-announcement/>.

## Data

Download the following files from the competition to `buttercup/data/`

- `litellm_backup.sql`
- `redis-backup.rdb`
- `task-storage.tar`

## Get Task IDs for Specific Projects

For example, find the Task IDs for `libpng`.

```shell
cd data/
../scripts/results_unpack.sh
../scripts/results_find.sh libpng
```

## Parse

Query the CRS database for submissions. Documentation can be found at <https://redis.io/learn/explore/import#restore-an-rdb-file>.

Let's assume a task ID `0197b76a-b429-78fa-8d0e-ad84994c8f44` was outputted from above.

1. Start `redis-server` in `data/` directory

   ```shell
   cd data/
   redis-server
   ```

1. Print directory to confirm

   ```shell
   redis-cli config get dir
   1) "dir"
   2) "<path/to/data>"
   ```

1. Stop `redis-server` and check if `dump.rdb` exists in `data/` directory.

1. Copy `.rdb` file

   ```shell
   cp redis-backup.rdb dump.rdb
   ```

1. Start `redis-server` and query to make sure it has data.

   ```shell
   redis-server
   redis-cli keys \*
   ```

1. Parse database for task id

   ```shell
   cd common/
   uv sync --all-extras
   uv run buttercup-util read_submissions --task_id 0197b76a-b429-78fa-8d0e-ad84994c8f44 --verbose True > ../data/submissions.txt
   ```

1. Read through `submissions.txt` for information like crash harnesses, stacktraces, and patches.
