#!/bin/sh
set -eu

: "${REDIS_ADMIN_PASSWORD:?}" "${REDIS_APP_PASSWORD:?}" "${REDIS_EXPORTER_PASSWORD:?}"

sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

mkdir -p /run/redis
cat > /run/redis/users.acl <<ACL
user default off
user admin on #$(sha "$REDIS_ADMIN_PASSWORD") ~* &* +@all
user app on #$(sha "$REDIS_APP_PASSWORD") ~book:* ~top:* ~genres:* ~lock:* resetchannels -@all +@connection +get +set +del +unlink +exists +ttl +pttl +evalsha +eval +script|load +script|exists
user exporter on #$(sha "$REDIS_EXPORTER_PASSWORD") ~* &* -@all +@connection +memory -readonly +strlen +config|get +xinfo +pfcount -quit +zcard +type +xlen -readwrite -command +command|info +client -wait +scard +llen +hlen +arcount +get +eval +slowlog +cluster|info +cluster|slots +cluster|nodes -hello -echo +info +latency +scan -reset -auth -asking
ACL
chown -R redis:redis /run/redis 2>/dev/null || true
chmod 600 /run/redis/users.acl

exec docker-entrypoint.sh redis-server /usr/local/etc/redis/redis.conf
