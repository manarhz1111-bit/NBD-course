from __future__ import annotations

import math
import statistics
import time

from . import catalog, store
from .encoder import Encoder
from .report import table
from .settings import Settings

K = 10
CROSS_LINGUAL = (
    "удобное кресло для чтения",
    "мягкий диван для гостиной",
    "уличные стулья для сада",
    "зеркало в ванную",
)


def dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def score(ids: list[int], gains: dict[int, float]) -> dict[str, float]:
    got = [gains.get(i, 0.0) for i in ids[:K]]
    ideal = dcg(sorted(gains.values(), reverse=True)[:K])
    first = next((r for r, g in enumerate(got, start=1) if g == 1.0), None)
    return {
        "ndcg": dcg(got) / ideal if ideal else 0.0,
        "p5": sum(1 for g in got[:5] if g == 1.0) / 5,
        "hit1": 1.0 if got and got[0] == 1.0 else 0.0,
        "mrr": 1 / first if first else 0.0,
    }


def run(settings: Settings) -> dict:
    _, queries = catalog.build(settings.data_dir, settings.catalog_size, settings.eval_queries)
    encoder = Encoder(settings)
    client = store.connect(settings.qdrant_url, settings.qdrant_api_key)
    encoded = [(q, encoder.dense_query(q.text), encoder.sparse_query(q.text)) for q in queries]

    rows, summary = [], {}
    for mode in store.MODES:
        scores, latencies = [], []
        for q, dense, sparse in encoded:
            started = time.perf_counter()
            points = store.search(client, settings.collection, mode, dense, sparse, limit=K)
            latencies.append((time.perf_counter() - started) * 1000)
            scores.append(score([int(p.id) for p in points], q.gains))
        mean = {m: statistics.mean(s[m] for s in scores) for m in scores[0]}
        summary[mode] = {m: round(v, 3) for m, v in mean.items()}
        rows.append([mode, len(scores), f"{mean['ndcg']:.3f}", f"{mean['p5']:.3f}", f"{mean['hit1']:.3f}",
                     f"{mean['mrr']:.3f}", f"{statistics.median(latencies):.1f}"])

    overlaps = []
    for _, dense, _ in encoded:
        approx = {p.id for p in store.search(client, settings.collection, "dense", dense, limit=K)}
        exact = {p.id for p in store.search(client, settings.collection, "dense", dense, limit=K, exact=True)}
        overlaps.append(len(approx & exact) / K)
    info = client.get_collection(settings.collection)

    lines = [f"{len(queries)} WANDS queries with human labels (Exact = 1, Partial = 0.5, Irrelevant = 0), top {K}"]
    lines += table(["mode", "queries", f"nDCG@{K}", "P@5 exact", "hit@1 exact", f"MRR@{K}", "qdrant ms (median)"], rows)
    lines.append(f"dense HNSW recall@{K} against exact search: {statistics.mean(overlaps):.3f}"
                 f" (points {info.points_count}, indexed vectors {info.indexed_vectors_count})")
    lines.append("russian queries against the english catalogue (dense model is multilingual):")
    for text in CROSS_LINGUAL:
        points = store.search(client, settings.collection, "dense", encoder.dense_query(text), limit=3)
        lines.append(f"  {text} -> " + " | ".join(p.payload["name"] for p in points))
    return {"lines": lines, "summary": summary}
