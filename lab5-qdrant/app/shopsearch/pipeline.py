from __future__ import annotations

import time
from collections import Counter

from . import catalog, store
from .encoder import Encoder
from .settings import Settings

FILES = ("product.csv", "query.csv", "label.csv")


def warmup(settings: Settings) -> dict:
    started = time.monotonic()
    encoder = Encoder(settings)
    marker = settings.model_dir / ".ready"
    marker.write_text(f"{settings.dense_model}\n{settings.sparse_model}\n", encoding="utf-8")
    return {
        "dense_model": settings.dense_model,
        "sparse_model": f"{settings.sparse_model} ({settings.sparse_language})",
        "dimension": encoder.dimension,
        "seconds": round(time.monotonic() - started, 1),
    }


def ingest(settings: Settings, recreate: bool = False) -> dict:
    missing = [f for f in FILES if not (settings.data_dir / f).is_file()]
    if missing:
        raise SystemExit(f"missing dataset files in {settings.data_dir}: {', '.join(missing)}")
    started = time.monotonic()
    products, queries = catalog.build(settings.data_dir, settings.catalog_size, settings.eval_queries)
    parsed = time.monotonic()
    encoder = Encoder(settings)
    texts = [p.embedding_text() for p in products]
    dense = encoder.dense_documents(texts)
    embedded_dense = time.monotonic()
    sparse = encoder.sparse_documents(texts)
    embedded = time.monotonic()
    client = store.connect(settings.qdrant_url, settings.qdrant_api_key)
    created = store.create_collection(client, settings.collection, encoder.dimension, recreate=recreate)
    store.upsert(client, settings.collection, products, dense, sparse)
    done = time.monotonic()
    info = client.get_collection(settings.collection)
    return {
        "collection": settings.collection,
        "created": created,
        "products": len(products),
        "eval_queries": len(queries),
        "judged_in_catalog": sum(len(q.gains) for q in queries),
        "top_categories": dict(Counter(p.category or "Other" for p in products).most_common(5)),
        "with_rating": sum(1 for p in products if p.rating is not None),
        "points_in_collection": info.points_count,
        "seconds": {
            "parse": round(parsed - started, 1),
            "dense_embedding": round(embedded_dense - parsed, 1),
            "sparse_embedding": round(embedded - embedded_dense, 1),
            "upsert": round(done - embedded, 1),
        },
        "products_per_second_dense": round(len(products) / max(embedded_dense - parsed, 1e-9), 1),
    }
