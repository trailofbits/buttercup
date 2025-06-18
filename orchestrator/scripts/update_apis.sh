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

# Update competition API client
# Run docker with current user to ensure correct file permissions
USER_ID=$(id -u)
GROUP_ID=$(id -g)
docker run --rm --user $USER_ID:$GROUP_ID -v "$(realpath example-crs-architecture/docs/api):/local" -v "$OUTPUT_DIR/src/buttercup/orchestrator:/out" openapitools/openapi-generator-cli generate \
    -i /local/competition-swagger-v1.4.0.json \
    -g python \
    -o /out \
    --package-name competition_api_client

sed -i.bak 's/^from competition_api_client/from buttercup.orchestrator.competition_api_client/' $(find $OUTPUT_DIR/src/buttercup/orchestrator -name '*.py')
sed -i.bak 's/competition_api_client.models,/buttercup.orchestrator.competition_api_client.models,/' $(find $OUTPUT_DIR/src/buttercup/orchestrator -name '*.py')
sed -i.bak 's/^import competition_api_client/import buttercup.orchestrator.competition_api_client/' $(find $OUTPUT_DIR/src/buttercup/orchestrator -name '*.py')
sed -i.bak 's/^from competition_api_client/from buttercup.orchestrator.competition_api_client/' $(find $OUTPUT_DIR/src/buttercup/orchestrator -name '*.md')
sed -i.bak 's/^import competition_api_client./import buttercup.orchestrator.competition_api_client./' $(find $OUTPUT_DIR/src/buttercup/orchestrator -name '*.md')

mkdir -p "$OUTPUT_DIR/docs"
mkdir -p "$OUTPUT_DIR/test"
cp -rv "$OUTPUT_DIR"/src/buttercup/orchestrator/docs/* "$OUTPUT_DIR/docs/"
cp -rv "$OUTPUT_DIR"/src/buttercup/orchestrator/test/* "$OUTPUT_DIR/test/"
rm -rf "$OUTPUT_DIR/src/buttercup/orchestrator/docs"
rm -rf "$OUTPUT_DIR/src/buttercup/orchestrator/test"

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
