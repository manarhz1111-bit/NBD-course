from prometheus_client import Counter, Gauge, Histogram

LATENCY_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)

HTTP_REQUESTS = Counter("app_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency, split by what the cache did for the request",
    ["method", "route", "cache"],
    buckets=LATENCY_BUCKETS,
)


CACHE_REQUESTS = Counter("app_cache_requests_total", "Cache lookups by entity and result", ["entity", "result"])
CACHE_ERRORS = Counter("app_cache_errors_total", "Redis errors (the request fell back to PostgreSQL)", ["op"])
CACHE_INVALIDATIONS = Counter("app_cache_invalidations_total", "Keys deleted after a write", ["entity"])
CACHE_REFRESH_AHEAD = Counter(
    "app_cache_refresh_ahead_total", "Background rebuilds started before the key expired", ["entity"]
)
CACHE_BREAKER_OPEN = Gauge("app_cache_breaker_open", "1 while the Redis circuit breaker is open")

DB_QUERY_LATENCY = Histogram(
    "app_db_query_duration_seconds",
    "PostgreSQL query latency",
    ["query"],
    buckets=LATENCY_BUCKETS,
)
DB_POOL_SIZE = Gauge("app_db_pool_size", "Connections currently open in the pool")
DB_POOL_AVAILABLE = Gauge("app_db_pool_available", "Idle connections in the pool")
DB_POOL_WAITING = Gauge("app_db_pool_requests_waiting", "Requests waiting for a connection")
