# General telemetry guidance

1. All work performed on challenges should be described by spans, and these spans must specify `round.id`, `task.id`, `crs.action.category` and `crs.action.name` (teams are free to choose their own names for
   crs.action.name, but it should be descriptive of the kind of work being performed)
1. Spans/Traces should not be used for general-purpose logging. Use OpenTelemetry Logs for this purpose.
1. All LLM requests' telemetry must be linked to a parent span that describes a unit of work that the LLM request contributes towards.

## Improving the structure of OTEL data

1. A trace is made up of spans that share a `trace_id` , and a trace must describe a distinct non-trivial effort that is mapped to a single `task.id`. Said differently: a trace should not span across multiple tasks, but
   a single task may have multiple traces.
   1. A trace may have one or more “root spans” (a span with no `parent_span_id`), but a single root span per trace is preferred.
   1. A trace should encompass a non-trivial number of spans. A small number of spans in a trace should indicate unusual or exceptional behavior.
1. Spans must be linked to indicate relationships between spans either via parent/child relationships or via span links
   1. A parent/child relationship indicated by `parent_span_id` is expected for all units of work that are nested under a larger unit of work (e.g. function calls under an API endpoint, or LLM queries to service an
      asynchronous task).
   1. In cases where a multiple spans contribute to a new unit of work, or spans have a causal relationship (asynchronous, sequential, etc), span `links` must be used instead of parent/child relationships.
   1. In order for the telemetry data to be meaningful, the links between spans must reflect the order and hierarchy of work performed. This means that span relationships should generally form tree-like graphs rather
      than unlinked spans. Accomplishing this may require adding a telemetry span at a higher logical level in order to properly describe the hierarchy of work performed.

## Verifying telemetry

On your team's SigNoz server, you may check for the following attributes: `crs.action.category`, `round.id`, `task.id`, & `gen_ai.request.model` as a general means to verify the requested telemetry is being provided.

These attributes provide the following:

- `crs.action.category` attribute confirms CRS telemetry spans were sent
- `round.id/task.id` are examples of attributes from a Task's `metadata` field. These need to be supplied in the spans. (confirms correct task metadata field passthrough)
- `gen_ai.request.model` attribute existing confirms LLM telemetry
