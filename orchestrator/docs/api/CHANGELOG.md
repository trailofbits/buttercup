# Changelog

## 1.4.0

- Added new request endpoint for rerunning real challenges

## 1.3.1

- Document already-existing limit on accepted `engine` in PoVs

## 1.3.0

- Introduce `inconclusive` submission status. This status highlights when a test job ran excessively long (8+ hours). It is meant to distinguish inconclusive status from failures and errors. A CRS should not conclude anything
  about their submission's quality when receiving this status. The status also highlights to the organizers that the submission needs manual review.
- Update some descriptions to better highlight endpoint & field use
- Introduce an explicit type for 200 responses

## 1.2.0

- revert to the default SARIF schema removing the required property on `ruleId`
- add endpoint for requesting an integration test challenge

## v1.1.1

- correct typo in swagger docs tags for freeform submission

## v1.1

- add ping endpoint to test network connectivity and credentials
- crs status endpoint requires authentication

## v1.0

- add freeform submission
- add freeform submission to bundle
- add `harnesses_included` boolean to task broadcasts
- **BREAKING CHANGE**: add new required `engine` field to pov submission. valid values are found in the `project.yaml`

## v0.4

- added bundle workflow
- removed SARIF Broadcast ID, Vuln ID, and description from patch submission
- renamed vuln submissions to pov submissions
- renamed sarif assessments to broadcast-sarif-assessments
- removed sarif submissions from vuln
- added new endpoint for sarif submissions
- added new errored state to possible statuses for server-side testing errors

For more information, see:

- [The v0.4 readme](./api-v0.4-readme.md)
- [The v0.4 OpenAPI specification](./competition-swagger-v0.4.yaml)

## v0.3

- Change invalid / valid in SARIF assessment to correct / incorrect
- Rename Vuln Broadcast to SARIF Broadcast
- Removed `vuln_id` from SARIF broadcast, added a `task_id` and a `sarif_id`
- Made `vuln_id`optional on Patch Submissions
- Added optional `sarif_id` on patch submissions
- Added large max sizes to most string fields on the Competition API
- Added note that max sizes for base64 fields are before encoding
- Added metadata fields to Task and SARIF broadcasts containing a string to string map that should be attached to outputs like log messages and OpenTelemetry trace attributes for traceability
- Added `focus` and `project_name` to Task broadcasts.
  - Project name is the OSS Fuzz project name for the task.
  - Focus is the name of the directory in the `repo` tarball that vulns, patches, and SARIF broadcasts should be submitted against.
- Started usage of an enhanced JSON schema for SARIFs. It is a more strict version of the original, requiring a `ruleId` be set on each result.
- Added a reset stats endpoint
- Added a cancel all running tasks endpoint
- Reworked status endpoint
  - Added a `since` field tracking the last Unix timestamp it was reset
  - Reworked counter fields to allow more fine grained tracking and provided definitions for each field
