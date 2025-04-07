# Buttercup Common utilities

## Protobufs

The `protos` directory contains the protobuf definitions for various messages used by the Buttercup system.

## Buttercup Util utility

The `buttercup-util` script is a utility for interacting with various components of the Buttercup CRS.

```bash
$ buttercup-util --help
usage: buttercup-util [-h] [--redis_url str] [--log_level str] {send_queue,read_queue,list_queues,delete_queue,add_harness,add_build,read_harnesses,read_builds} ...

options:
  -h, --help            show this help message and exit
  --redis_url str       Redis URL (default: redis://localhost:6379)
  --log_level str       Log level (default: info)

subcommands:
  {send_queue,read_queue,list_queues,delete_queue,add_harness,add_build,read_harnesses,read_builds}
    send_queue
    read_queue
    list_queues
    delete_queue
    add_harness
    add_build
    read_harnesses
    read_builds
```

### Send messages to a specific queue

```bash
$ buttercup-util send_queue orchestrator_download_tasks_queue ./examples/task_download.txt 
2025-03-12 10:49:46,342 - buttercup.common.util_cli - INFO - Reading TaskDownload message from file 'examples/task_download.txt'
2025-03-12 10:49:46,342 - buttercup.common.util_cli - INFO - Pushing message to queue 'orchestrator_download_tasks_queue': task {
  message_time: 1739917788000
  task_id: "my-task-id"
  task_type: TASK_TYPE_DELTA
  sources {
    sha256: "c516e2b73f58fe163be48f5bc0ca36995ee100c752e30883f9acaa0a95ca2bb6"
    url: "https://challengesact.blob.core.windows.net/challenges/c516e2b73f58fe163be48f5bc0ca36995ee100c752e30883f9acaa0a95ca2bb6.tar.gz?se=2025-08-18T22%3A29%3A44Z&sp=r&sv=2022-11-02&sr=b&sig=7lj49Z6vXsFuKp4DqVrVVMwHU4xEAQJ%2BSCZ7BAQnbvY%3D"
  }
  sources {
    sha256: "910913fd13eb2e7cb7ca9a39fce4cc753d54579c938a5c60d478788101fdde3e"
    source_type: SOURCE_TYPE_FUZZ_TOOLING
    url: "https://challengesact.blob.core.windows.net/challenges/910913fd13eb2e7cb7ca9a39fce4cc753d54579c938a5c60d478788101fdde3e.tar.gz?se=2025-08-18T22%3A29%3A47Z&sp=r&sv=2022-11-02&sr=b&sig=M6JoI0pGccbSARTqVLm23yQZUbUwsQsFyBpRMoADnYc%3D"
  }
  sources {
    sha256: "04ffd1402d868846d6812112c4bc2ec50722aa1adfaf02aab7233ad20bd1b495"
    source_type: SOURCE_TYPE_DIFF
    url: "https://challengesact.blob.core.windows.net/challenges/04ffd1402d868846d6812112c4bc2ec50722aa1adfaf02aab7233ad20bd1b495.tar.gz?se=2025-08-18T22%3A29%3A42Z&sp=r&sv=2022-11-02&sr=b&sig=M63mfyTls1CJhxelj%2BdtGmmO9fIVimybM6yqOMCkRac%3D"
  }
  deadline: 1739932188000
  project_name: "libpng"
  focus: "example-libpng"
}
```

### Read an entire queue

```bash
$ buttercup-util read_queue orchestrator_download_tasks_queue
[...]
```

Or, if you want to simulate a consumer in a consumer group popping an element out of the queue:
```bash
$ buttercup-util read_queue orchestrator_download_tasks_queue --group_name orchestrator_group
```

### Add an harness to the fuzzer map

```bash
$ buttercup-util add_harness ./examples/weighted_harness.txt
2025-03-12 10:53:10,256 - buttercup.common.util_cli - INFO - Added harness weight for libpng | libpng_read_fuzzer | my-task-id
```

```bash
$ buttercup-util read_harnesses
weight: 1.0
package_name: "libpng"
harness_name: "libpng_read_fuzzer"
task_id: "my-task-id"

2025-03-12 10:55:35,483 - buttercup.common.util_cli - INFO - Done
```

### Add a build to the build map

```bash
$ buttercup-util add_build ./examples/build.txt 
2025-03-12 10:55:07,273 - buttercup.common.util_cli - INFO - Added build for my-task-id | fuzzer | address
```

```bash
$ buttercup-util read_builds my-task-id fuzzer
engine: "libfuzzer"
sanitizer: "address"
task_dir: "/crs_scratch/my-task-id/"
task_id: "my-task-id"
build_type: "FUZZER"
apply_diff: true

2025-03-12 10:55:20,298 - buttercup.common.util_cli - INFO - Done
```
