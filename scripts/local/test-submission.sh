#!/usr/bin/env bash
# Test the complete submission pipeline

set -e

echo "🧪 Testing CRS Submission Pipeline"
echo "=================================="

# Check if services are running
echo "1️⃣ Checking CRS services..."
if ! docker compose ps | grep -q "unified-fuzzer.*Up"; then
    echo "❌ CRS services not running. Start them first:"
    echo "   docker compose up -d"
    echo ""
    echo "Current service status:"
    docker compose ps
    exit 1
fi
echo "✅ Services are running"

# Submit the crashy project
echo -e "\n2️⃣ Submitting crashy-project..."
./scripts/local/submit.sh example-challenges/crashy-project

# Give the system time to process
echo -e "\n3️⃣ Waiting for initial processing..."
sleep 10

# Check download logs
echo -e "\n4️⃣ Checking task downloads..."
docker compose logs task-downloader --tail 50 | grep -E "(Downloading|Downloaded)" || echo "No downloads yet"

# Check build activity
echo -e "\n5️⃣ Checking fuzzer build activity..."
docker compose logs unified-fuzzer --tail 50 | grep -E "(Building|Built|Compiling)" || echo "No build activity yet"

# Monitor for crashes
echo -e "\n6️⃣ Starting live monitoring for crashes..."
echo "   This will monitor for 30 seconds..."

# Run monitor in background
timeout 30 ./scripts/local/monitor.sh --no-services || true

# Check final results
echo -e "\n7️⃣ Final check for crashes in Redis..."
docker compose exec redis redis-cli LLEN crashes_queue

echo -e "\n✅ Test complete! Check the output above for:"
echo "   - File downloads from the submission server"
echo "   - Build activity in the fuzzer"
echo "   - Any crashes found"
echo ""
echo "For detailed logs, run:"
echo "   docker compose logs -f unified-fuzzer"
echo "   docker compose logs -f task-downloader"