from __future__ import annotations

import statistics
import time

import numpy as np
from qdrant_client import QdrantClient, models

from . import store
from .report import table
from .settings import Settings

NAME = "bench"
TOP = 10


def synthetic(n: int, dim: int, clusters: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(clusters, dim)).astype(np.float32)
    labels = rng.integers(0, clusters, size=n)
    data = centers[labels] + rng.normal(scale=0.6, size=(n, dim)).astype(np.float32)
    return data / np.linalg.norm(data, axis=1, keepdims=True)


def wait_green(client: QdrantClient, expected: int, timeout: float = 1800) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        info = client.get_collection(NAME)
        if info.status == models.CollectionStatus.GREEN and (info.indexed_vectors_count or 0) >= expected:
            return time.monotonic() - started
        time.sleep(1)
    raise TimeoutError("bench collection did not finish indexing")


def measure(client: QdrantClient, queries: np.ndarray, truth: np.ndarray, params: models.SearchParams) -> tuple[float, float, float]:
    recalls, latencies = [], []
    for query, expected in zip(queries, truth):
        started = time.perf_counter()
        points = client.query_points(NAME, query=query.tolist(), search_params=params, limit=TOP).points
        latencies.append((time.perf_counter() - started) * 1000)
        recalls.append(len({p.id for p in points} & set(expected.tolist())) / TOP)
    latencies.sort()
    return statistics.mean(recalls), statistics.median(latencies), latencies[int(0.95 * len(latencies))]


def run(settings: Settings, n: int = 100_000, dim: int = 384, queries: int = 200) -> list[str]:
    client = store.connect(settings.qdrant_url, settings.qdrant_api_key, grpc=True, timeout=300)
    data = synthetic(n, dim, clusters=max(n // 500, 50))
    rng = np.random.default_rng(11)
    probe = data[rng.choice(n, size=queries, replace=False)] + rng.normal(scale=0.05, size=(queries, dim)).astype(np.float32)
    probe /= np.linalg.norm(probe, axis=1, keepdims=True)
    truth = np.argsort(-(probe @ data.T), axis=1)[:, :TOP]

    if client.collection_exists(NAME):
        client.delete_collection(NAME)
    client.create_collection(
        NAME,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
        optimizers_config=models.OptimizersConfigDiff(indexing_threshold=1_000),
    )
    started = time.monotonic()
    client.upload_collection(NAME, vectors=data, ids=range(n), batch_size=1024, parallel=1, wait=True)
    uploaded = time.monotonic() - started
    indexed = wait_green(client, n)

    rows = []
    recall, p50, p95 = measure(client, probe, truth, models.SearchParams(exact=True))
    rows.append(["exact (full scan)", "-", f"{recall:.3f}", f"{p50:.2f}", f"{p95:.2f}"])
    for ef in (16, 32, 64, 128, 256):
        recall, p50, p95 = measure(client, probe, truth, models.SearchParams(hnsw_ef=ef))
        rows.append(["hnsw float32", ef, f"{recall:.3f}", f"{p50:.2f}", f"{p95:.2f}"])

    client.update_collection(
        NAME,
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, quantile=0.99, always_ram=True)
        ),
    )
    time.sleep(2)
    quantized = wait_green(client, n)
    for ef in (64, 128):
        for rescore in (False, True):
            params = models.SearchParams(
                hnsw_ef=ef,
                quantization=models.QuantizationSearchParams(rescore=rescore, oversampling=2.0 if rescore else None),
            )
            recall, p50, p95 = measure(client, probe, truth, params)
            rows.append([f"hnsw int8{' + rescore' if rescore else ''}", ef, f"{recall:.3f}", f"{p50:.2f}", f"{p95:.2f}"])

    raw_mb = n * dim * 4 / 2**20
    lines = [
        f"bench: {n} vectors x {dim} dims, {queries} queries, recall@{TOP} against numpy brute force",
        f"upload {uploaded:.1f} s ({n / uploaded:.0f} points/s), HNSW build {indexed:.1f} s, int8 rebuild {quantized:.1f} s",
        f"vector memory: float32 {raw_mb:.0f} MiB, int8 {raw_mb / 4:.0f} MiB",
        *table(["search", "hnsw_ef", f"recall@{TOP}", "p50 ms", "p95 ms"], rows),
    ]
    client.close()
    return lines
