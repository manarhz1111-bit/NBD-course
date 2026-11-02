#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_pw="$APP_DB_PASSWORD" -v exp_pw="$EXPORTER_DB_PASSWORD" <<'SQL'
CREATE ROLE lab3_app LOGIN PASSWORD :'app_pw' CONNECTION LIMIT 40;
GRANT CONNECT ON DATABASE library TO lab3_app;
GRANT USAGE ON SCHEMA public TO lab3_app;
GRANT SELECT ON authors, books, reviews TO lab3_app;
GRANT UPDATE (price, updated_at) ON books TO lab3_app;
GRANT INSERT (book_id, rating, body) ON reviews TO lab3_app;
CREATE ROLE lab3_exporter LOGIN PASSWORD :'exp_pw' CONNECTION LIMIT 10;
GRANT pg_monitor TO lab3_exporter;
SQL
