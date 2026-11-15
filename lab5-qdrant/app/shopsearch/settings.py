from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class Settings:
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL", "http://127.0.0.1:6333"))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY"))
    collection: str = field(default_factory=lambda: _env("QDRANT_COLLECTION", "products"))
    model_dir: Path = field(default_factory=lambda: Path(_env("MODEL_DIR", "/opt/lab5-search/models")))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/opt/lab5-search/data")))
    dense_model: str = field(default_factory=lambda: _env("DENSE_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"))
    sparse_model: str = field(default_factory=lambda: _env("SPARSE_MODEL", "Qdrant/bm25"))
    sparse_language: str = field(default_factory=lambda: _env("SPARSE_LANGUAGE", "english"))
    embed_threads: int = field(default_factory=lambda: int(_env("EMBED_THREADS", "2")))
    catalog_size: int = field(default_factory=lambda: int(_env("CATALOG_SIZE", "12000")))
    eval_queries: int = field(default_factory=lambda: int(_env("EVAL_QUERIES", "60")))
