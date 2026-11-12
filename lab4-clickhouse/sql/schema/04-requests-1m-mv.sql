CREATE MATERIALIZED VIEW IF NOT EXISTS lab4.requests_1m_mv
TO lab4.requests_1m
DEFINER = default SQL SECURITY DEFINER
AS SELECT
    toStartOfMinute(toDateTime(ts)) AS minute,
    service,
    endpoint,
    count() AS requests,
    countIf(status >= 500) AS server_errors,
    countIf(status >= 400 AND status < 500) AS client_errors,
    sum(toUInt64(bytes_sent)) AS bytes_sent,
    max(duration_ms) AS max_ms,
    quantilesTDigestState(0.5, 0.95, 0.99)(duration_ms) AS duration,
    uniqState(user_id) AS users
FROM lab4.requests
GROUP BY minute, service, endpoint
