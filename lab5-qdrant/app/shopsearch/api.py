from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

from . import store
from .encoder import Encoder
from .settings import Settings

BUCKETS = (0.002, 0.005, 0.01, 0.02, 0.035, 0.05, 0.075, 0.1, 0.15, 0.25, 0.4, 0.6, 1.0, 2.0, 5.0)

REQUESTS = Counter("lab5_search_requests", "Search requests", ["mode", "status"])
LATENCY = Histogram("lab5_search_duration_seconds", "Search latency by stage", ["mode", "stage"], buckets=BUCKETS)
TOP_SCORE = Histogram("lab5_search_top_score", "Score of the best hit", ["mode"],
                      buckets=(0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 2.0, 5.0, 10.0, 20.0))
EMPTY = Counter("lab5_search_empty", "Searches that returned nothing", ["mode"])
IN_FLIGHT = Gauge("lab5_search_in_flight", "Searches being processed")
READY = Gauge("lab5_search_ready", "1 when the model is loaded and the collection is reachable")


class Hit(BaseModel):
    id: int
    score: float
    name: str
    product_class: str
    category: str
    rating: float | None
    reviews: int
    snippet: str


class Answer(BaseModel):
    query: str
    mode: str
    took_ms: dict[str, float]
    hits: list[Hit]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    app.state.encoder = Encoder(settings)
    app.state.client = store.connect(settings.qdrant_url, settings.qdrant_api_key, timeout=10)
    READY.set(1 if app.state.client.collection_exists(settings.collection) else 0)
    yield
    app.state.client.close()


app = FastAPI(title="Product search", version="1.0", lifespan=lifespan)


def snippet(text: str, size: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size].rsplit(" ", 1)[0] + " …"


@app.get("/search", response_model=Answer)
def search(
    q: Annotated[str, Query(min_length=2, max_length=500)],
    mode: store.Mode = "hybrid",
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    category: Annotated[str | None, Query(max_length=100)] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
) -> Answer:
    settings: Settings = app.state.settings
    encoder: Encoder = app.state.encoder
    IN_FLIGHT.inc()
    started = time.perf_counter()
    try:
        dense = encoder.dense_query(q) if mode != "sparse" else None
        sparse = encoder.sparse_query(q) if mode != "dense" else None
        embedded = time.perf_counter()
        points = store.search(app.state.client, settings.collection, mode, dense, sparse, limit=limit,
                              category=category, min_rating=min_rating)
        finished = time.perf_counter()
    except Exception as error:
        REQUESTS.labels(mode, "error").inc()
        raise HTTPException(status_code=503, detail=f"search failed: {type(error).__name__}") from error
    finally:
        IN_FLIGHT.dec()

    LATENCY.labels(mode, "embed").observe(embedded - started)
    LATENCY.labels(mode, "qdrant").observe(finished - embedded)
    LATENCY.labels(mode, "total").observe(finished - started)
    REQUESTS.labels(mode, "ok").inc()
    if points:
        TOP_SCORE.labels(mode).observe(points[0].score)
    else:
        EMPTY.labels(mode).inc()

    return Answer(
        query=q,
        mode=mode,
        took_ms={
            "embed": round((embedded - started) * 1000, 2),
            "qdrant": round((finished - embedded) * 1000, 2),
            "total": round((finished - started) * 1000, 2),
        },
        hits=[
            Hit(
                id=int(p.id),
                score=round(p.score, 4),
                name=p.payload["name"],
                product_class=p.payload["product_class"],
                category=p.payload["category"],
                rating=p.payload.get("rating"),
                reviews=p.payload.get("reviews", 0),
                snippet=snippet(p.payload.get("description", "")),
            )
            for p in points
        ],
    )


@app.get("/healthz")
def healthz() -> dict:
    settings: Settings = app.state.settings
    try:
        info = app.state.client.get_collection(settings.collection)
    except Exception as error:
        READY.set(0)
        raise HTTPException(status_code=503, detail=f"qdrant unavailable: {type(error).__name__}") from error
    READY.set(1)
    return {"status": "ok", "collection": settings.collection, "points": info.points_count, "segments": info.segments_count}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
