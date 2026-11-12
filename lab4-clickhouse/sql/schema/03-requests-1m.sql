CREATE TABLE IF NOT EXISTS lab4.requests_1m
(
    minute        DateTime('UTC'),
    service       LowCardinality(String),
    endpoint      LowCardinality(String),
    requests      SimpleAggregateFunction(sum, UInt64),
    server_errors SimpleAggregateFunction(sum, UInt64),
    client_errors SimpleAggregateFunction(sum, UInt64),
    bytes_sent    SimpleAggregateFunction(sum, UInt64),
    max_ms        SimpleAggregateFunction(max, Float32),
    duration      AggregateFunction(quantilesTDigest(0.5, 0.95, 0.99), Float32),
    users         AggregateFunction(uniq, UInt32)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(minute)
ORDER BY (service, endpoint, minute)
TTL minute + INTERVAL 180 DAY DELETE
