CREATE TABLE IF NOT EXISTS lab4.deployments
(
    ts      DateTime('UTC'),
    service LowCardinality(String),
    version LowCardinality(String),
    kind    Enum8('deploy' = 1, 'rollback' = 2)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (service, ts)
TTL ts + INTERVAL 180 DAY DELETE
