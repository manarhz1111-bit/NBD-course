CREATE TABLE IF NOT EXISTS lab4.requests
(
    ts          DateTime64(3, 'UTC') CODEC(Delta(8), ZSTD(1)),
    service     LowCardinality(String),
    endpoint    LowCardinality(String),
    method      Enum8('GET' = 1, 'POST' = 2, 'PUT' = 3, 'DELETE' = 4),
    status      UInt16 CODEC(T64, ZSTD(1)),
    duration_ms Float32 CODEC(Gorilla, ZSTD(1)),
    bytes_sent  UInt32 CODEC(T64, ZSTD(1)),
    region      LowCardinality(String),
    pod         LowCardinality(String),
    version     LowCardinality(String),
    user_id     UInt32 CODEC(T64, ZSTD(1)),
    trace_id    UUID,
    error       LowCardinality(String),
    INDEX idx_trace trace_id TYPE bloom_filter(0.01) GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toDate(ts)
ORDER BY (service, endpoint, ts)
PRIMARY KEY (service, endpoint, ts)
TTL toDateTime(ts) + INTERVAL 14 DAY DELETE
SETTINGS ttl_only_drop_parts = 1
