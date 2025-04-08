#!/bin/bash

# Check if task ID is provided
if [ "$#" -ne 1 ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    echo "Usage: $0 <task_id>"
    echo ""
    echo "Sends a SARIF report to the competition API for the given task ID"
    echo ""
    echo "Note: Requires port-forwarding to the competition API to be active."
    echo "Run this first: kubectl port-forward -n crs service/buttercup-competition-api 31323:1323"
    exit 1
fi

TASK_ID="$1"

# The $TASK_ID won't be substituted in single quotes, let's use a JSON file
JSON_DATA=$(cat <<EOF
{
  "task_id": "${TASK_ID}",
  "sarif": {
    "runs": [
      {
        "artifacts": [
          {
            "location": {
              "index": 0,
              "uri": "pngrutil.c"
            }
          }
        ],
        "automationDetails": {
          "id": "/"
        },
        "conversion": {
          "tool": {
            "driver": {
              "name": "GitHub Code Scanning"
            }
          }
        },
        "results": [
          {
            "correlationGuid": "9d13d264-74f2-48cc-a3b9-d45a8221b3e1",
            "level": "error",
            "locations": [
              {
                "physicalLocation": {
                  "artifactLocation": {
                    "index": 0,
                    "uri": "pngrutil.c"
                  },
                  "region": {
                    "endLine": 1447,
                    "startColumn": 1,
                    "startLine": 1421
                  }
                }
              }
            ],
            "message": {
              "text": "Associated risk: CWE-121"
            },
            "partialFingerprints": {
              "primaryLocationLineHash": "22ac9f8e7c3a3bd8:8"
            },
            "properties": {
              "github/alertNumber": 2,
              "github/alertUrl": "https://api.github.com/repos/aixcc-finals/example-libpng/code-scanning/alerts/2"
            },
            "rule": {
              "id": "CWE-121",
              "index": 0
            },
            "ruleId": "CWE-121"
          }
        ],
        "tool": {
          "driver": {
            "name": "CodeScan++",
            "rules": [
              {
                "defaultConfiguration": {
                  "level": "warning"
                },
                "fullDescription": {
                  "text": "vulnerable to #CWE-121"
                },
                "helpUri": "https://example.com/help/png_handle_iCCP",
                "id": "CWE-121",
                "properties": {},
                "shortDescription": {
                  "text": "CWE #CWE-121"
                }
              }
            ],
            "version": "1.0.0"
          }
        },
        "versionControlProvenance": [
          {
            "branch": "refs/heads/challenges/full-scan",
            "repositoryUri": "https://github.com/aixcc-finals/example-libpng",
            "revisionId": "fdacd5a1dcff42175117d674b0fda9f8a005ae88"
          }
        ]
      }
    ],
    "": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
    "version": "2.1.0"
  }
}
EOF
)

curl -X 'POST' 'http://localhost:31323/webhook/sarif' \
  -H 'Content-Type: application/json' \
  -d "$JSON_DATA"