#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.." && . scripts/lib.sh
CACHE_NS=$(curl -fsS --max-time 15 "$API/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["cache_namespace"])') || exit 1

BOOK=42
KEY="book:${CACHE_NS}:$BOOK"

say "Health"
req GET /health; echo "  $BODY"
expect "postgres and redis up" "$(echo "$BODY" | grep -o '"status":"[a-z]*"')" '"status":"ok"'

say "Read-through: first read misses, second hits"
rcli DEL "$KEY" > /dev/null
req GET /books/$BOOK;  expect "1st read" "$XCACHE" MISS; FIRST=$MS
req GET /books/$BOOK;  expect "2nd read" "$XCACHE" HIT
echo "  miss ${FIRST} ms -> hit ${MS} ms"
echo "  TTL of $KEY: $(rcli TTL "$KEY") s (base 3600 s +-10% jitter)"
echo "  value: $(rcli GET "$KEY" | cut -c1-140)..."

say "Write invalidates the cached copy"
NEWPRICE="$(awk 'BEGIN { srand(); printf "%.2f", 10 + rand() * 50 }')"
req PUT /books/$BOOK/price "{\"price\": $NEWPRICE}"; expect "update" "$STATUS" 200
expect "key deleted after write" "$(rcli EXISTS "$KEY")" 0
req GET /books/$BOOK;  expect "read after write" "$XCACHE" MISS
GOT=$(echo "$BODY" | grep -o '"price":[0-9.]*' | cut -d: -f2)
expect "new price $NEWPRICE is visible" "$(awk -v a="$GOT" -v b="$NEWPRICE" 'BEGIN { print (a + 0 == b + 0) ? "yes" : a }')" yes
req GET /books/$BOOK;  expect "and is cached again" "$XCACHE" HIT

say "Negative caching (cache penetration)"
MISSING=999999
rcli DEL "book:${CACHE_NS}:$MISSING" > /dev/null
req GET /books/$MISSING; expect "unknown id" "$STATUS/$XCACHE" 404/MISS
req GET /books/$MISSING; expect "second time from cache" "$STATUS/$XCACHE" 404/NEGATIVE_HIT
echo "  stored marker: $(rcli GET "book:${CACHE_NS}:$MISSING"), TTL $(rcli TTL "book:${CACHE_NS}:$MISSING") s"

say "Expensive aggregate: top books of a genre"
rcli DEL "top:${CACHE_NS}:fantasy" > /dev/null
req GET "/genres/fantasy/top?limit=5"; expect "first" "$XCACHE" MISS; FIRST=$MS
req GET "/genres/fantasy/top?limit=5"; expect "second" "$XCACHE" HIT
echo "  miss ${FIRST} ms -> hit ${MS} ms"

say "Bypass for comparison"
req GET "/books/$BOOK?cache=false"; expect "cache=false" "$XCACHE" BYPASS

say "Result"
if [ "$FAILS" -eq 0 ]; then ok "all checks passed"; else bad "$FAILS check(s) failed"; exit 1; fi
