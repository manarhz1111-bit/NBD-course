from __future__ import annotations

from collections.abc import Sequence

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import models

from .settings import Settings


class Encoder:
    def __init__(self, settings: Settings):
        settings.model_dir.mkdir(parents=True, exist_ok=True)
        cache = str(settings.model_dir)
        self.dense_model = settings.dense_model
        self.dense = TextEmbedding(settings.dense_model, cache_dir=cache, threads=settings.embed_threads)
        self.sparse = SparseTextEmbedding(settings.sparse_model, cache_dir=cache, language=settings.sparse_language)
        self.dimension = len(self.dense_query("probe"))

    def dense_query(self, text: str) -> list[float]:
        return next(iter(self.dense.query_embed(text))).tolist()

    def sparse_query(self, text: str) -> models.SparseVector:
        vector = next(iter(self.sparse.query_embed(text)))
        return models.SparseVector(indices=vector.indices.tolist(), values=vector.values.tolist())

    def dense_documents(self, texts: Sequence[str], batch_size: int = 32) -> list[list[float]]:
        return [v.tolist() for v in self.dense.embed(list(texts), batch_size=batch_size)]

    def sparse_documents(self, texts: Sequence[str], batch_size: int = 64) -> list[models.SparseVector]:
        return [
            models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())
            for v in self.sparse.embed(list(texts), batch_size=batch_size)
        ]
