# Buttercup Common utilities

## Protobufs

The `protos` directory contains the protobuf definitions for various messages used by the Buttercup system.

## Message Publisher utility

The `buttercup-msg-publisher` script is a utility for pushing custom messages to a queue.

```bash
$ buttercup-msg-publisher list
```

```bash
$ cat /tmp/msg.proto
task {
  message_id: "my-message-id"
  message_time: 123
  task_id: "my-task-id"
  task_type: TASK_TYPE_DELTA
  sources {
    url: "https://github.com/buttercup-project/buttercup"
  }
  sources {
    source_type: SOURCE_TYPE_FUZZ_TOOLING
    url: "https://github.com/buttercup-project/fuzz-tooling"
  }
  sources {
    source_type: SOURCE_TYPE_DIFF
    url: "https://github.com/buttercup-project/diff"
  }
  deadline: 123
}
$ buttercup-msg-publisher send tasks_ready_queue /tmp/msg.proto
2025-01-28 13:38:37,674 - buttercup.common.msg_publisher - INFO - Reading TaskReady message from file '/tmp/msg.proto'
2025-01-28 13:38:37,675 - buttercup.common.msg_publisher - INFO - Pushing message to queue 'tasks_ready_queue': task {
  message_id: "my-message-id"
  message_time: 123
  task_id: "my-task-id"
  task_type: TASK_TYPE_DELTA
  sources {
    url: "https://github.com/buttercup-project/buttercup"
  }
  sources {
    source_type: SOURCE_TYPE_FUZZ_TOOLING
    url: "https://github.com/buttercup-project/fuzz-tooling"
  }
  sources {
    source_type: SOURCE_TYPE_DIFF
    url: "https://github.com/buttercup-project/diff"
  }
  deadline: 123
}

```
