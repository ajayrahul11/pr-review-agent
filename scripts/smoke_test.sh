#!/usr/bin/env bash
# Post-deploy smoke test: health + one real review through all four agents on Bedrock.
# Usage: BASE_URL=http://... API_KEY=... ./scripts/smoke_test.sh
set -euo pipefail
: "${BASE_URL:?}" "${API_KEY:?}"

for i in $(seq 1 30); do
  curl -fsS "$BASE_URL/health" && break || sleep 10
done
echo

resp=$(curl -fsS -X POST "$BASE_URL/reviews" -H "x-api-key: $API_KEY" \
  -H 'content-type: application/json' \
  -d "{\"pull_request\": $(cat data/fixtures/sample_pr.json)}")
status=$(echo "$resp" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["status"])')
verified=$(echo "$resp" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["metrics"].get("FixesVerified", 0))')
echo "status=$status fixes_verified=$verified"
[[ "$status" == "pending_approval" || "$status" == "posted" || "$status" == "approved" ]]
[[ "${verified%.*}" -ge 1 ]]
echo "smoke test passed"
