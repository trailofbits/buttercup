

sleep 9000

# Second request - delta task
echo "=========================================" | tee -a "$OUTPUT_FILE"
echo "Second request (delta task) at $(date)" | tee -a "$OUTPUT_FILE"
echo "=========================================" | tee -a "$OUTPUT_FILE"

RESPONSE2=$(curl -s -w "\nHTTP_CODE:%{http_code}\nTIME:%{time_total}\n" -X 'POST' "$API_URL" \
  -H 'Content-Type: application/json' \
  -d '{
    "challenge_repo_url": "https://github.com/tob-challenges/afc-freerdp",
    "challenge_repo_base_ref": "a92cc0f3ebc3d3f4cf5b6097920a391e9b5fcfcf",
    "challenge_repo_head_ref": "challenges/fp-delta-01",
    "fuzz_tooling_url": "https://github.com/trail-of-forks/oss-fuzz",
    "fuzz_tooling_ref": "master",
    "fuzz_tooling_project_name": "freerdp",
    "duration": 7200
}')

echo "$RESPONSE2" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"
echo "Response: $RESPONSE2" 

echo "=========================================" | tee -a "$OUTPUT_FILE"
echo "All requests completed at $(date)" | tee -a "$OUTPUT_FILE"
echo "Responses saved to: $OUTPUT_FILE" | tee -a "$OUTPUT_FILE"

