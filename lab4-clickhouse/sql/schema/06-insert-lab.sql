CREATE TABLE IF NOT EXISTS lab4.insert_lab AS lab4.requests
ENGINE = MergeTree
PARTITION BY toDate(ts)
ORDER BY (service, endpoint, ts)
