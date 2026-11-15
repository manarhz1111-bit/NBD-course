from __future__ import annotations

import asyncio
import itertools
import os
import statistics
import time
from dataclasses import dataclass, field

import httpx

from .encoder import Encoder
from .catalog import read_queries
from .report import table
from .settings import Settings


@dataclass
class Stage:
    name: str
    concurrency: int
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    seconds: float = 0.0

    def row(self) -> list[object]:
        done = len(self.latencies)
        ordered = sorted(self.latencies) or [0.0]

        def pct(p: float) -> str:
            return f"{ordered[min(len(ordered) - 1, int(p * len(ordered)))] * 1000:.1f}"

        return [
            self.name,
            self.concurrency,
            done,
            self.errors,
            f"{done / self.seconds:.1f}",
            f"{statistics.median(ordered) * 1000:.1f}",
            pct(0.95),
            pct(0.99),
        ]


HEADERS = ["target", "conc", "requests", "errors", "rps", "p50 ms", "p95 ms", "p99 ms"]


async def drive(stage: Stage, duration: float, call) -> Stage:
    deadline = time.perf_counter() + duration
    counter = itertools.count()

    async def worker() -> None:
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            try:
                response = await call(next(counter))
                ok = response.status_code == 200
            except httpx.HTTPError:
                ok = False
            if ok:
                stage.latencies.append(time.perf_counter() - started)
            else:
                stage.errors += 1

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(stage.concurrency)))
    stage.seconds = time.perf_counter() - started
    return stage


def qdrant_body(mode: str, dense: list[float], sparse, limit: int = 5) -> dict:
    sparse_json = {"indices": list(sparse.indices), "values": list(sparse.values)}
    if mode == "dense":
        return {"query": dense, "using": "dense", "limit": limit, "with_payload": True}
    if mode == "sparse":
        return {"query": sparse_json, "using": "bm25", "limit": limit, "with_payload": True}
    depth = max(limit * 4, 20)
    return {
        "prefetch": [
            {"query": dense, "using": "dense", "limit": depth},
            {"query": sparse_json, "using": "bm25", "limit": depth},
        ],
        "query": {"rrf": {"k": 60}},
        "limit": limit,
        "with_payload": True,
    }


async def run_async(settings: Settings, duration: float, levels: list[int]) -> list[str]:
    api_url = os.environ.get("SEARCH_URL", "http://127.0.0.1:8085")
    questions = [q.text for q in read_queries(settings.data_dir)]
    encoder = Encoder(settings)
    vectors = [(encoder.dense_query(q), encoder.sparse_query(q)) for q in questions]
    limits = httpx.Limits(max_connections=max(levels) * 2, max_keepalive_connections=max(levels) * 2)
    lines: list[str] = []

    async with httpx.AsyncClient(base_url=api_url, timeout=30, limits=limits) as api:
        await api.get("/healthz")
        rows = []
        for conc in levels:
            stage = await drive(Stage("api hybrid", conc), duration,
                                lambda i: api.get("/search", params={"q": questions[i % len(questions)], "mode": "hybrid"}))
            rows.append(stage.row())
        lines += ["Search API (embedding + Qdrant), mode=hybrid", *table(HEADERS, rows), ""]

        rows = []
        conc = levels[len(levels) // 2]
        for mode in ("dense", "sparse", "hybrid"):
            stage = await drive(Stage(f"api {mode}", conc), duration,
                                lambda i, m=mode: api.get("/search", params={"q": questions[i % len(questions)], "mode": m}))
            rows.append(stage.row())
        lines += [f"Search API by mode, concurrency={conc}", *table(HEADERS, rows), ""]

    headers = {"api-key": settings.qdrant_api_key, "accept-encoding": "identity"}
    path = f"/collections/{settings.collection}/points/query"
    async with httpx.AsyncClient(base_url=settings.qdrant_url, headers=headers, timeout=30, limits=limits) as qd:
        rows = []
        for mode in ("dense", "sparse", "hybrid"):
            bodies = [qdrant_body(mode, d, s) for d, s in vectors]
            for conc in (levels[0], max(levels)):
                stage = await drive(Stage(f"qdrant {mode}", conc), duration,
                                    lambda i, b=bodies: qd.post(path, json=b[i % len(b)]))
                rows.append(stage.row())
        lines += ["Qdrant REST directly (vectors precomputed)", *table(HEADERS, rows)]
    return lines


def run(settings: Settings, duration: float = 15.0, levels: list[int] | None = None) -> list[str]:
    return asyncio.run(run_async(settings, duration, levels or [1, 2, 4, 8, 16]))
