#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-http://localhost:8080}"
API_KEY="${ECHRYN_API_KEY:-change-me}"
curl -fsS "$BASE_URL/healthz" | python -m json.tool
curl -fsS -X POST "$BASE_URL/v1/extractions/sync" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  -d '{"url":"https://www.instagram.com/reel/Dd10cOlujGD/","mode":"metadata"}' | python -m json.tool
