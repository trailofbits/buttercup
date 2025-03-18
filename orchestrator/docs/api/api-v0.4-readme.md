# Competition API v0.4

## Competition API Endpoints

### Proof of Vulnerability

#### Changes in v0.4

- The optional SARIF field has been moved to its own endpoint.
- This endpoint moved from `/v1/task/<task_id>/vuln` to `/v1/task/<task_id>/pov` to remove use of the overloaded term "vulnerability".
- Initial returned submission status can never be `invalid`.
- The `invalid` status was removed since there was no way for it to be hit.
- There is a new status `errored` indicating a server-side issue when testing a PoV. If you see this status, your CRS should resubmit.
- Two fields have been renamed to match the corresponding argument names from OSSFuzz’s `helper.py`: `data_file` is now `testcase` and `harness_name` is now `fuzzer_name`.

#### Submission

```javascript
POST /v1/task/<task_id>/pov

{
    "testcase": "base64 data",
    "fuzzer_name": "which harness to pass the data file to",
    "sanitizer": "which sanitizer to build the project with",
    "architecture": "x86_64", # required to be this value
}
```

##### Response

Submissions that do not fit the schema will receive a 400 error describing the schema mismatch. They do not receive an ID.

All complete and on-time submissions will get an `accepted` status back. Submissions after the deadline will get `deadline_exceeeded`.

```javascript
200 OK
{
    "pov_id": "<uuid>",
    "status": "accepted" | "deadline_exceeded"
}
```

#### Status

```javascript
GET /v1/task/<task_id>/pov/<pov_id>
```

##### Response

Requests for a nonexistent `pov_id` will get a 404 back with no body.

The additional statuses which submissions can enter over time are:

- `passed`: the submission was tested and all tests passed.
- `failed`: the submission was tested and failed at least one test.
- `errored`: the submission was tested and there was a server-side error testing it.

```javascript
200 OK
{
    "pov_id": "<uuid>",
    "status": "accepted" | "passed" | "failed" | "deadline_exceeded" | "errored"
}
```

### Patch

#### Changes in v0.4

- The optional proof of vulnerability ID, broadcast SARIF ID, and plaintext description have been moved to a separate endpoint (the `bundle` endpoint).
- Functionality test results are now available to competitors separate from overall patch status.

#### Submission

```javascript
POST /v1/task/<task_id>/patch

{
    "patch": "base64 data"
}
```

##### Response

Submissions that do not fit the schema will receive a 400 error describing the schema mismatch. They do not receive an ID.

All complete and on-time submissions will get an `accepted` status back. Submissions after the deadline will get `deadline_exceeeded`.

```javascript
200 OK
{
    "patch_id": "<uuid>",
    "status": "accepted" | "deadline_exceeded"
}
```

#### Status

```javascript
GET /v1/task/<task_id>/patch/<patch_id>
```

##### Response

Requests for a nonexistent `patch_id` will get a 404 back with no body.

The additional statuses which submissions can enter over time are:

- `passed`: the submission applied, the project built, and the functionality tests passed.
- `failed`: the submission failed to apply, build, or pass the tests.
- `errored`: there was a server-side error testing the submission.

There is an additional field, `functionality_tests_passing`, which contains a separate status for the functionality tests. The overall patch status still includes the functionality test result (i.e. the functionality
tests must have passed for the patch to be `passed`).

If the functionality tests have not been run, the `functionality_tests_passing` field will be `null`.

```javascript
{
    "patch_id": "<uuid>",
    "status": "accepted" | "passed" | "failed" | "deadline_exceeded" | "errored",
    "functionality_tests_passing": true | false | null
}
```

### Broadcast SARIF Assessment

#### Changes in v0.4

- SARIFs sent to CRSs are now referred to as "broadcast SARIFs" to distinguish them from those submitted by the CRS.
- This endpoint moved from `/v1/task/<task_id>/sarif/<sarif_id>` to `/v1/task/<task_id>/broadcast-sarif-assessment/<broadcast_sarif_id>`
- It is worth noting that only Broadcast SARIFs can be assessed using this endpoint. CRS-submitted SARIFs receive an ID (via a separate endpoint which is new in v0.4) but that ID cannot be used with this endpoint.

#### Submission

```javascript
POST /v1/task/<task_id>/broadcast-sarif-assessment/<broadcast_sarif_id>
```

##### Response

Broadcast SARIF Assessments do not return an ID since there is no further action to be taken with them.

Submissions that do not fit the schema will receive a 400 error describing the schema mismatch. They do not receive an ID.

All complete and on-time submissions will get an `accepted` status back. Submissions after the deadline will get `deadline_exceeeded`.

```javascript
200 OK
{
    "status": "accepted" | "deadline_exceeded"
}
```

### SARIF Submission

#### Changes in v0.4

- CRS-submitted SARIFs are now referred to as "submitted SARIFs" to distinguish them from those broadcasted by the Competition Infrastructure ("broadcast SARIFs").
- This endpoint is brand new in v0.4, but it should receive the content your CRS was already sending via the Proof of Vulnerability Submission Endpoint's optional SARIF field.
- Submitted SARIFs must use explicit rules, not just text descriptions attached to locations in code. Submitted SARIFs must have `rule_id` set on any `result` objects.

#### Submission

```javascript
POST /v1/task/<task_id>/submitted-sarif
{
    "sarif": {} # SARIF-formatted object.
}
```

##### Response

Submissions that do not fit the schema will receive a 400 error describing the schema mismatch. They do not receive an ID.

All complete and on-time submissions will get an `accepted` status back. Submissions after the deadline will get `deadline_exceeeded`.

```javascript
200 OK
{
    "submitted_sarif_id": "<uuid>",
    "status": "accepted" | "deadline_exceeded"
}
```

### Submission Association ("Bundling")

Previously, your CRS was able to submit SARIFs only when submitting vulnerabilities. It could also attach vulnerabilities it found, or broadcast SARIFs it received, to any patches it created later.

It could not:

- Submit patches first and attach vulnerabilities found later
- Submit patches first and attach broadcast SARIFs it received later (the organizers think this will be a common use case)
- Submit vulnerabilities first and attach SARIFs generated later

It could also not attach SARIFs to patches it generated. There were several associations the organizers wanted to enable CRSs to make that were not possible.

This endpoint introduces a new entity called a "bundle" which represents an association of any subset of other entities (broadcast SARIF, submitted SARIF, patch, and proof of vulnerability).

#### Creation

All fields are optional, but new bundles containing less than two items are rejected with a 400 error and do not receive an ID.

```javascript
POST /v1/task/<task_id>/bundle
{
    "pov_id": "<uuid>",
    "patch_id": "<uuid>",
    "submitted_sarif_id": "<uuid>",
    "broadcast_sarif_id": "<uuid>",
    "description": "optional plaintext description containing any additional information to explain the CRS's findings"
}
```

##### Response

Bundles that do not fit the schema will receive a 400 error describing the schema mismatch. They do not receive an ID.

All complete and on-time submissions will get an `accepted` status back. Submissions after the deadline will get `deadline_exceeeded`.

```javascript
200 OK
{
    "bundle_id": "<uuid>",
    "status": "accepted" | "deadline_exceeded"
}
```

#### Adding to a bundle

Already created bundles can have any of their fields changed, additional fields set, or any field unset.

Pass only the fields you want to modify. Other fields will be unchanged.

Patching with an invalid schema will return a 400\.

Patching a field to `null` unsets it.

```javascript
PATCH /v1/task/<task_id>/bundle/<bundle_id>
{
    "pov_id": "<uuid>" | null,
    "patch_id": "<uuid>" | null,
    "submitted_sarif_id": "<uuid>" | null,
    "broadcast_sarif_id": "<uuid>" | null,
    "description": "optional plaintext description of the components of the bundle, such as would be found in a pull request description or bug report" | null
}
```

#### Status

Requests for a nonexistent `bundle_id` will get a 404 back with no body.

This endpoint returns the content of the bundle with a couple of additional fields to describe the status of the bundle.

```javascript
GET /v1/task/<task_id>/bundle/<bundle_id>
```

##### Response

```javascript
200 OK
{
    "pov_id": "<uuid>",
    "patch_id": "<uuid>",
    "submitted_sarif_id": "<uuid>",
    "broadcast_sarif_id": "<uuid>",
    "description": "optional plaintext description of the components of the bundle, such as would be found in a pull request description or bug report",
    "status": "accepted" | "deadline_exceeded"
}
```

#### Deleting a bundle

Requests for a nonexistent `bundle_id` will get a 404 back with no body.

```javascript
DELETE /v1/task/<task_id>/bundle/<bundle_id>
```

##### Response

```javascript
204 No Content
```
