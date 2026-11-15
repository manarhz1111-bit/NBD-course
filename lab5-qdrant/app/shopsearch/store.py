from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Literal

from qdrant_client import QdrantClient, models

from .catalog import Product

DENSE = "dense"
SPARSE = "bm25"
Mode = Literal["dense", "sparse", "hybrid"]
MODES: tuple[Mode, ...] = ("dense", "sparse", "hybrid")
PAYLOAD_INDEXES = {
    "category": models.PayloadSchemaType.KEYWORD,
    "product_class": models.PayloadSchemaType.KEYWORD,
    "rating": models.PayloadSchemaType.FLOAT,
    "reviews": models.PayloadSchemaType.INTEGER,
}

warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")


def connect(url: str, api_key: str, grpc: bool = False, timeout: int = 60) -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key, prefer_grpc=grpc, timeout=timeout, check_compatibility=False)


def create_collection(client: QdrantClient, name: str, dimension: int, recreate: bool = False) -> bool:
    if client.collection_exists(name):
        if not recreate:
            return False
        client.delete_collection(name)
    client.create_collection(
        collection_name=name,
        vectors_config={DENSE: models.VectorParams(size=dimension, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
        optimizers_config=models.OptimizersConfigDiff(indexing_threshold=1_000),
        on_disk_payload=True,
    )
    for field, schema in PAYLOAD_INDEXES.items():
        client.create_payload_index(name, field_name=field, field_schema=schema, wait=True)
    return True


def upsert(
    client: QdrantClient,
    name: str,
    products: Sequence[Product],
    dense: Sequence[list[float]],
    sparse: Sequence[models.SparseVector],
    batch_size: int = 128,
) -> int:
    for start in range(0, len(products), batch_size):
        window = slice(start, start + batch_size)
        points = [
            models.PointStruct(id=p.id, vector={DENSE: d, SPARSE: s}, payload=p.payload())
            for p, d, s in zip(products[window], dense[window], sparse[window])
        ]
        client.upsert(name, points=points, wait=True)
    return len(products)


def build_filter(category: str | None = None, min_rating: float | None = None) -> models.Filter | None:
    must: list[models.Condition] = []
    if category:
        must.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    if min_rating is not None:
        must.append(models.FieldCondition(key="rating", range=models.Range(gte=min_rating)))
    return models.Filter(must=must) if must else None


def search(
    client: QdrantClient,
    name: str,
    mode: Mode,
    dense: list[float] | None = None,
    sparse: models.SparseVector | None = None,
    limit: int = 5,
    category: str | None = None,
    min_rating: float | None = None,
    exact: bool = False,
    hnsw_ef: int | None = None,
) -> list[models.ScoredPoint]:
    flt = build_filter(category, min_rating)
    params = models.SearchParams(exact=exact, hnsw_ef=hnsw_ef)
    if mode == "dense":
        response = client.query_points(name, query=dense, using=DENSE, query_filter=flt, search_params=params, limit=limit)
    elif mode == "sparse":
        response = client.query_points(name, query=sparse, using=SPARSE, query_filter=flt, limit=limit)
    else:
        depth = max(limit * 4, 20)
        response = client.query_points(
            name,
            prefetch=[
                models.Prefetch(query=dense, using=DENSE, filter=flt, params=params, limit=depth),
                models.Prefetch(query=sparse, using=SPARSE, filter=flt, limit=depth),
            ],
            query=models.RrfQuery(rrf=models.Rrf(k=60)),
            limit=limit,
        )
    return response.points
