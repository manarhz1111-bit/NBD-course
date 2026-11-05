#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
. scripts/lib.sh
CACHE_NS=$(curl -fsS --max-time 15 "$API/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["cache_namespace"])') || exit 1
N="${N:-200}"
GENRE="${GENRE:-history}"
Q='app_db_query_duration_seconds_count{query="top"}'

burst() {
  local mode="$1" tmp t0 t1 i status xc
  tmp=$(mktemp -d) || exit 1
  t0=$(date +%s%N)

  seq "$N" | xargs -P "$N" -I{} bash -c '
    curl -sS --max-time 60 -o /dev/null -D "$2/$3.headers" \
      -w "%{http_code}" "$1" > "$2/$3.status"
  ' _ "$API/genres/$GENRE/top?limit=3&cache=$mode" "$tmp" {} || true

  MISSES=0
  BAD_RESPONSES=0
  : > "$tmp/results"

  for ((i=1; i<=N; i++)); do
    status=$(cat "$tmp/$i.status" 2>/dev/null)
    xc=$(awk -F': ' 'tolower($1)=="x-cache" {gsub(/\r/, "", $2); print $2}' \
      "$tmp/$i.headers" 2>/dev/null)

    printf '%s %s\n' "${status:-000}" "${xc:-NO_HEADER}" >> "$tmp/results"
    [[ "$xc" == MISS ]] && MISSES=$((MISSES + 1))

    if [[ "$status" != 200 ]]; then
      BAD_RESPONSES=$((BAD_RESPONSES + 1))
    elif [[ "$mode" == true ]]; then
      case "$xc" in
        MISS|HIT|WAIT_HIT) ;;
        *) BAD_RESPONSES=$((BAD_RESPONSES + 1)) ;;
      esac
    fi
  done

  sort "$tmp/results" | uniq -c |
    awk '{printf "  %s requests: HTTP %s X-Cache=%s\n", $1, $2, $3}'

  t1=$(date +%s%N)
  echo "  wall time for $N requests: $(((t1 - t0) / 1000000)) ms"
  rm -rf "$tmp"
}

settle() {
  for _ in $(seq 1 30); do
    if [[ "$(metric app_db_pool_requests_waiting)" == 0 &&
          "$(metric app_db_pool_available)" == "$(metric app_db_pool_size)" ]]; then
      return 0
    fi
    sleep 1
  done
  bad "database pool did not settle"
  return 1
}

say "1) With cache: $N concurrent requests on a missing key"
settle || exit 1
rcli DEL "top:${CACHE_NS}:$GENRE" "lock:top:${CACHE_NS}:$GENRE" > /dev/null || exit 1

BEFORE=$(metric "$Q")
burst true
AFTER=$(metric "$Q")
WITH=$(awk -v a="$AFTER" -v b="$BEFORE" 'BEGIN {print a-b}')

expect "all $N requests returned 200 with MISS/HIT/WAIT_HIT" "$BAD_RESPONSES" 0
expect "exactly one MISS" "$MISSES" 1
expect "exactly one DB loader attempt" "$WITH" 1

say "2) Without cache: same burst (503 responses are reported)"
settle || exit 1
BEFORE=$(metric "$Q")
burst false
AFTER=$(metric "$Q")
WITHOUT=$(awk -v a="$AFTER" -v b="$BEFORE" 'BEGIN {print a-b}')

echo "  DB loader attempts, including pool rejections: $WITHOUT"
echo "  non-200 or failed requests: $BAD_RESPONSES of $N"

say "Result"
if [[ "$FAILS" -eq 0 ]]; then
  ok "all cache stampede checks passed"
else
  bad "$FAILS check(s) failed"
  exit 1
fi
