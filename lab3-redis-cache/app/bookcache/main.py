from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from redis.asyncio import BlockingConnectionPool, Redis
from redis.backoff import NoBackoff
from redis.asyncio.retry import Retry
from psycopg_pool import PoolTimeout, TooManyRequests
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError

from . import db
from .cache import Cache
from .config import settings
from .metrics import HTTP_LATENCY, HTTP_REQUESTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bookcache")

TOP_CACHED_ROWS = 50


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.pool.open(wait=True, timeout=30)

    pool = BlockingConnectionPool(
        host=settings.redis_host,
        port=settings.redis_port,
        username=settings.redis_user,
        password=settings.redis_password or None,
        decode_responses=True,
        socket_timeout=settings.redis_timeout_s,
        socket_connect_timeout=settings.redis_timeout_s,
        max_connections=settings.redis_max_connections,
        timeout=settings.redis_pool_timeout_s,
        retry=Retry(NoBackoff(), 1, supported_errors=(RedisConnectionError,)),
        health_check_interval=15,
        client_name="bookcache-api",
    )
    redis = Redis(connection_pool=pool)
    app.state.redis = redis
    app.state.cache = Cache(redis, settings)
    log.info(
        "started: cache_enabled=%s pool=%s..%s", settings.cache_enabled, settings.pg_pool_min, settings.pg_pool_max
    )
    yield
    await redis.aclose()
    await db.pool.close()


app = FastAPI(title="Lab 3 - library catalogue with Redis cache-aside", lifespan=lifespan)


@app.exception_handler(PoolTimeout)
@app.exception_handler(TooManyRequests)
async def db_overloaded(request: Request, exc: Exception):
    return JSONResponse(
        {"detail": "database overloaded, retry later"},
        status_code=503,
        headers={"Retry-After": "1", "X-Cache": "OVERLOAD"},
    )


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    if route_path != "/metrics":
        cache_result = response.headers.get("X-Cache", "none").lower()
        HTTP_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route_path, cache_result).observe(time.perf_counter() - start)
    return response


def _cache(request: Request) -> Cache:
    return request.app.state.cache


UseCache = Annotated[bool, Query(description="false = read PostgreSQL directly (for comparison)")]


@app.get("/books/{book_id}")
async def get_book(request: Request, response: Response, book_id: Annotated[int, Path(ge=1)], cache: UseCache = True):
    c = _cache(request)
    book, result = await c.get_or_load(
        "book", c.book_key(book_id), settings.book_ttl_s, lambda: db.get_book(book_id), use_cache=cache
    )
    if book is None:
        raise HTTPException(404, f"book {book_id} not found", headers={"X-Cache": result.upper()})
    response.headers["X-Cache"] = result.upper()
    return book


@app.get("/genres/{genre}/top")
async def top_books(
    request: Request,
    response: Response,
    genre: str,
    limit: Annotated[int, Query(ge=1, le=TOP_CACHED_ROWS)] = 10,
    cache: UseCache = True,
):
    genre = genre.lower()
    c = _cache(request)
    rows, result = await c.get_or_load(
        "top",
        c.top_key(genre),
        settings.top_ttl_s,
        lambda: db.get_top(genre, TOP_CACHED_ROWS),
        use_cache=cache,
        refresh_ahead=True,
    )
    response.headers["X-Cache"] = result.upper()
    return {"genre": genre, "items": rows[:limit]}


@app.get("/genres")
async def genres(request: Request, response: Response, cache: UseCache = True):
    c = _cache(request)
    rows, result = await c.get_or_load("genres", c.genres_key(), settings.genres_ttl_s, db.get_genres, use_cache=cache)
    response.headers["X-Cache"] = result.upper()
    return rows


class PriceIn(BaseModel):
    price: Decimal = Field(gt=0, lt=100_000, max_digits=7, decimal_places=2)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=2000)


@app.put("/books/{book_id}/price")
async def update_price(request: Request, book_id: Annotated[int, Path(ge=1)], body: Annotated[PriceIn, Body()]):
    row = await db.update_price(book_id, body.price)
    if row is None:
        raise HTTPException(404, f"book {book_id} not found")
    c = _cache(request)
    await c.invalidate("book", c.book_key(book_id))
    return {"id": book_id, "price": float(body.price), "invalidated": c.book_key(book_id)}


@app.post("/books/{book_id}/reviews", status_code=201)
async def add_review(request: Request, book_id: Annotated[int, Path(ge=1)], body: Annotated[ReviewIn, Body()]):
    row = await db.add_review(book_id, body.rating, body.text)
    if row is None:
        raise HTTPException(404, f"book {book_id} not found")
    c = _cache(request)

    await c.invalidate("book", c.book_key(book_id))
    await c.invalidate("top", c.top_key(row["genre"]))
    return {"id": row["id"], "book_id": book_id}


@app.get("/health")
async def health(request: Request):
    status = {"postgres": "down", "redis": "down"}
    try:
        async with db.pool.connection() as conn:
            await conn.execute("SELECT 1")
        status["postgres"] = "up"
    except Exception as exc:
        log.warning("health: postgres %s", exc)
    try:
        await request.app.state.redis.ping()
        status["redis"] = "up"
    except RedisError:
        pass

    code = 200 if status["postgres"] == "up" else 503
    status["status"] = "ok" if all(v == "up" for v in status.values()) else ("degraded" if code == 200 else "down")
    status["cache_namespace"] = _cache(request).namespace
    return JSONResponse(status, status_code=code)


@app.get("/metrics")
async def metrics():
    db.update_pool_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
