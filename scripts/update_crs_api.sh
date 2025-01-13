#!/bin/bash -x

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

TEMPDIR=$(mktemp -d)
cd "$TEMPDIR" || exit 1

git clone git@github.com:aixcc-finals/example-crs-architecture.git

$PYTHON_CMD -m venv venv
. ./venv/bin/activate

pip install git+https://github.com/trail-of-forks/fastapi-code-generator
pip install uvicorn
pip install fastapi

curl -o openapi.json -X POST https://converter.swagger.io/api/convert -H "Content-Type: application/json" --data-binary "@example-crs-architecture/docs/api/crs-swagger-v0.1.json"

fastapi-codegen --input openapi.json --output $OUTPUT_DIR/crs_api

# replace `from .models` with `from crs_api.models`
mv $OUTPUT_DIR/crs_api/main.py $OUTPUT_DIR/crs_api/server.py

# replace `from .models` with `from crs_api.models` in server.py
sed -i.bak 's/from .models/from crs_api.models/g' $OUTPUT_DIR/crs_api/server.py
# remove `from uuid import UUID` and replace UUID with str
sed -i.bak '/from uuid import UUID/d' $OUTPUT_DIR/crs_api/models/types.py
sed -i.bak 's/UUID/str/g' $OUTPUT_DIR/crs_api/models/types.py

# apply HTTP auth patch
cd "$OUTPUT_DIR/crs_api" || exit 1
patch < "$OUTPUT_DIR/crs_api_auth.patch"

rm -rf "$TEMPDIR"
