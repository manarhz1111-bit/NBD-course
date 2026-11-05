from __future__ import annotations

import time
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .metrics import DB_POOL_AVAILABLE, DB_POOL_SIZE, DB_POOL_WAITING, DB_QUERY_LATENCY

pool = AsyncConnectionPool(
    settings.pg_dsn,
    min_size=settings.pg_pool_min,
    max_size=settings.pg_pool_max,
    timeout=settings.pg_pool_timeout_s,
    max_waiting=settings.pg_pool_max_waiting,
    kwargs={"row_factory": dict_row, "autocommit": True},
    open=False,
    name="library",
)

BOOK_SQL = """
SELECT b.id, b.title, b.genre, b.year, b.price::float8 AS price, b.isbn,
       a.id AS author_id, a.name AS author_name, a.country AS author_country,
       r.reviews_count, r.avg_rating
FROM books b
JOIN authors a ON a.id = b.author_id
CROSS JOIN LATERAL (
    SELECT count(*) AS reviews_count, round(avg(rating), 2)::float8 AS avg_rating
    FROM reviews WHERE book_id = b.id
) r
WHERE b.id = %(id)s
"""


TOP_SQL = """
SELECT b.id, b.title, a.name AS author_name,
       count(*) AS reviews_count, round(avg(r.rating), 2)::float8 AS avg_rating
FROM reviews r
JOIN books b ON b.id = r.book_id
JOIN authors a ON a.id = b.author_id
WHERE b.genre = %(genre)s
GROUP BY b.id, b.title, a.name
HAVING count(*) >= %(min_reviews)s
ORDER BY avg_rating DESC, reviews_count DESC, b.id
LIMIT %(limit)s
"""

GENRES_SQL = "SELECT genre, count(*) AS books FROM books GROUP BY genre ORDER BY genre"

UPDATE_PRICE_SQL = """
UPDATE books SET price = %(price)s, updated_at = now() WHERE id = %(id)s RETURNING id, genre
"""

INSERT_REVIEW_SQL = """
WITH inserted AS (
    INSERT INTO reviews (book_id, rating, body)
    SELECT b.id, %(rating)s, %(body)s
    FROM books b WHERE b.id = %(id)s
    RETURNING id, book_id
)
SELECT i.id, i.book_id, b.genre
FROM inserted i
JOIN books b ON b.id = i.book_id
"""


def update_pool_metrics() -> None:
    stats = pool.get_stats()
    DB_POOL_SIZE.set(stats.get("pool_size", 0))
    DB_POOL_AVAILABLE.set(stats.get("pool_available", 0))
    DB_POOL_WAITING.set(stats.get("requests_waiting", 0))


@asynccontextmanager
async def _timed(query: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        DB_QUERY_LATENCY.labels(query).observe(time.perf_counter() - start)


async def _fetch(query_name: str, sql: str, params: dict[str, Any], many: bool):
    async with _timed(query_name):
        async with pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return await (cur.fetchall() if many else cur.fetchone())


async def get_book(book_id: int) -> dict | None:
    return await _fetch("book", BOOK_SQL, {"id": book_id}, many=False)


async def get_top(genre: str, limit: int, min_reviews: int = 10) -> list[dict]:
    return await _fetch("top", TOP_SQL, {"genre": genre, "limit": limit, "min_reviews": min_reviews}, many=True)


async def get_genres() -> list[dict]:
    return await _fetch("genres", GENRES_SQL, {}, many=True)


async def update_price(book_id: int, price: Decimal) -> dict | None:
    return await _fetch("update_price", UPDATE_PRICE_SQL, {"id": book_id, "price": price}, many=False)


async def add_review(book_id: int, rating: int, body: str) -> dict | None:
    return await _fetch("insert_review", INSERT_REVIEW_SQL, {"id": book_id, "rating": rating, "body": body}, many=False)
