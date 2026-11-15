API="${API:-http://127.0.0.1:8000}"
if [ -z "${REDIS_CLI:-}" ]; then
  [ -f .env ] && . ./.env
  REDIS_CLI="docker compose exec -T redis redis-cli --no-auth-warning --user admin --pass ${REDIS_ADMIN_PASSWORD}"
fi
FAILS=0

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS + 1)); }
rcli() { $REDIS_CLI "$@"; }

req() {
  local out
  out=$(curl -s -o /tmp/lab3_body -D /tmp/lab3_hdr -w '%{http_code} %{time_total}' \
        -X "$1" ${3:+-H 'Content-Type: application/json' -d "$3"} "$API$2")
  STATUS=${out% *}
  MS=$(awk -v t="${out#* }" 'BEGIN { printf "%.1f", t * 1000 }')
  XCACHE=$(awk -F': ' 'tolower($1)=="x-cache" { gsub(/\r/, "", $2); print $2 }' /tmp/lab3_hdr)
  BODY=$(cat /tmp/lab3_body)
  printf '  %-6s %-38s -> %s  X-Cache=%-13s %7s ms\n' "$1" "$2" "$STATUS" "${XCACHE:--}" "$MS"
}

expect() {
  if [ "$2" = "$3" ]; then ok "$1 ($2)"; else bad "$1: got '$2', want '$3'"; fi
}

metric() {
  curl -s "$API/metrics" | awk -v m="$1" 'index($0, m" ")==1 { v=$2 } END { print v+0 }'
}
