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

# Check if the swagger file exists
SWAGGER_FILE="docs/api/competition-swagger-v1.4.0.yaml"
if [ ! -f "$SWAGGER_FILE" ]; then
    echo "Swagger file not found: $SWAGGER_FILE"
    echo "Please ensure the competition API swagger file is available"
    exit 1
fi

echo "Generating FastAPI competition API skeleton from $SWAGGER_FILE..."

# Create temporary directory
TEMPDIR=$(mktemp -d)

# Install required tools
$PYTHON_CMD -m venv "$TEMPDIR/venv"
. $TEMPDIR/venv/bin/activate

# Install fastapi-codegen and other dependencies
pip install git+https://github.com/trail-of-forks/fastapi-code-generator
pip install uvicorn
pip install fastapi
pip install pyyaml

# Convert YAML to JSON first
echo "Converting YAML to JSON..."
python3 -c "
import yaml
import json

with open('$SWAGGER_FILE', 'r') as f:
    yaml_content = yaml.safe_load(f)

with open('$TEMPDIR/swagger.json', 'w') as f:
    json.dump(yaml_content, f, indent=2)
"

# Convert Swagger 2.0 to OpenAPI 3.0 using the converter service
echo "Converting Swagger 2.0 to OpenAPI 3.0..."
curl -o "$TEMPDIR/openapi.json" -X POST https://converter.swagger.io/api/convert -H "Content-Type: application/json" --data-binary "@$TEMPDIR/swagger.json"

OPENAPI_FILE="$TEMPDIR/openapi.json"

# Generate FastAPI code
fastapi-codegen --input "$OPENAPI_FILE" --output "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api"

# Fix imports to use the correct package structure
find "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api" -name "*.py" -exec sed -i.bak 's/from .models/from buttercup.orchestrator.ui.competition_api.models/g' {} \;

# Remove UUID imports and replace with str (similar to existing pattern)
find "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api" -name "*.py" -exec sed -i.bak '/from uuid import UUID/d' {} \;
find "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api" -name "*.py" -exec sed -i.bak 's/UUID/str/g' {} \;

# Create __init__.py files if they don't exist
touch "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api/__init__.py"
touch "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api/models/__init__.py"

# Clean up temporary files
find "$OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api" -name "*.bak" -delete

echo "FastAPI competition API skeleton generated successfully!"
echo "Generated files are in: $OUTPUT_DIR/src/buttercup/orchestrator/ui/competition_api/"
echo ""
echo "Next steps:"
echo "1. Review and customize the generated main.py"
echo "2. Add authentication middleware if needed"
echo "3. Implement file serving for challenges"
echo "4. Add database integration for storing submissions"

rm -rf "$TEMPDIR"
