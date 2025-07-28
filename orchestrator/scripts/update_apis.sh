#!/bin/bash -xe

OUTPUT_DIR=$1

# Ensure python3.12 is installed
PYTHON_CMD="python3.12"
if ! command -v python3.12 &> /dev/null
then
    # Test if python refers to python3.12
    if ! python3 --version | grep "Python 3.12" &> /dev/null
    then
        echo "Python 3.12 is not installed"
        exit 1
    fi
    PYTHON_CMD="python3"
fi

# Get script path
SCRIPT_PATH=$(realpath "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

cd "$PROJECT_DIR" || exit 1

git clone git@github.com:aixcc-finals/example-crs-architecture.git || true
git -C example-crs-architecture pull

cp -rv example-crs-architecture/docs/ "$OUTPUT_DIR/src/buttercup/orchestrator/docs/"

TEMPDIR=$(mktemp -d)
$PYTHON_CMD -m venv "$TEMPDIR/venv"
. $TEMPDIR/venv/bin/activate

# Competition API client removed - no longer needed

# Update task_server APIs
pip install git+https://github.com/trail-of-forks/fastapi-code-generator
pip install uvicorn
pip install fastapi

TEMPDIR=$(mktemp -d)
curl -o "$TEMPDIR/openapi.json" -X POST https://converter.swagger.io/api/convert -H "Content-Type: application/json" --data-binary "@example-crs-architecture/docs/api/crs-swagger-v1.4.0.json"

fastapi-codegen --input "$TEMPDIR/openapi.json" --output "$OUTPUT_DIR/src/buttercup/orchestrator/task_server"

mv "$OUTPUT_DIR/src/buttercup/orchestrator/task_server/main.py" "$OUTPUT_DIR/src/buttercup/orchestrator/task_server/server.py"

# replace `from .models` with `from orchestrator.task_server.models` in server.py
sed -i.bak 's/from .models/from buttercup.orchestrator.task_server.models/g' "$OUTPUT_DIR/src/buttercup/orchestrator/task_server/server.py"
# remove `from uuid import UUID` and replace UUID with str
sed -i.bak '/from uuid import UUID/d' "$OUTPUT_DIR/src/buttercup/orchestrator/task_server/models/types.py"
sed -i.bak 's/UUID/str/g' "$OUTPUT_DIR/src/buttercup/orchestrator/task_server/models/types.py"

echo "Look at server.py and adjust as needed (HTTP auth, etc.)"

rm -rf "$TEMPDIR"
