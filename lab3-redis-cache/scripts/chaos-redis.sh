#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
. scripts/lib.sh

DOWN_FOR="${DOWN_FOR:-30}"
redis_stopped=0

cleanup() {
  if [[ "$redis_stopped" == 1 ]]; then
    docker compose start redis >/dev/null
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

say "Stopping Redis for ${DOWN_FOR}s"
redis_stopped=1
docker compose stop redis || exit 1

for i in $(seq 1 5); do
  req GET "/books/$((i * 11))"
  expect "book $((i * 11)) still answers without Redis" "$STATUS" 200
done

req GET /health
echo "  $BODY"
expect "health remains available" "$STATUS" 200

STATE=$(printf '%s' "$BODY" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("postgres"), d.get("redis"), d.get("status"))
') || STATE="invalid response"
expect "PostgreSQL up, Redis down, API degraded" "$STATE" "up down degraded"

sleep "$DOWN_FOR"

say "Starting Redis again"
docker compose start redis || exit 1
redis_stopped=0

say "Waiting for cache recovery"
recovered=0
for i in $(seq 1 30); do
  req GET /books/11
  if [[ "$STATUS" == 200 && "$XCACHE" == HIT ]]; then
    recovered=1
    break
  fi
  sleep 3
done
expect "cache is used again" "$recovered" 1

say "Result"
if [[ "$FAILS" -eq 0 ]]; then
  ok "all chaos checks passed"
else
  bad "$FAILS check(s) failed"
  exit 1
fi
