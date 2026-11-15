from __future__ import annotations

import csv
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

GAIN = {"Exact": 1.0, "Partial": 0.5, "Irrelevant": 0.0}
DESCRIPTION_WORDS = 24
SEED = 7


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    product_class: str
    category: str
    path: str
    description: str
    rating: float | None
    reviews: int

    def embedding_text(self) -> str:
        short = " ".join(self.description.split()[:DESCRIPTION_WORDS])
        return f"{self.name}. {self.product_class}. {self.path}. {short}"

    def payload(self) -> dict:
        return {
            "name": self.name,
            "product_class": self.product_class or "Other",
            "category": self.category or "Other",
            "path": self.path,
            "description": " ".join(self.description.split()[:60]),
            "rating": self.rating,
            "reviews": self.reviews,
        }


@dataclass(frozen=True)
class Query:
    id: int
    text: str
    gains: dict[int, float]


def _rows(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(1 << 30)
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def read_products(data_dir: Path) -> dict[int, Product]:
    products = {}
    for row in _rows(data_dir / "product.csv"):
        path = " / ".join(p.strip() for p in row["category hierarchy"].split("/") if p.strip())
        products[int(row["product_id"])] = Product(
            id=int(row["product_id"]),
            name=row["product_name"].strip(),
            product_class=row["product_class"].strip(),
            category=path.split(" / ")[0] if path else "",
            path=path,
            description=row["product_description"].strip(),
            rating=_number(row["average_rating"]),
            reviews=int(_number(row["review_count"]) or 0),
        )
    return products


def read_queries(data_dir: Path) -> list[Query]:
    texts = {int(r["query_id"]): r["query"].strip() for r in _rows(data_dir / "query.csv")}
    gains: dict[int, dict[int, float]] = defaultdict(dict)
    for row in _rows(data_dir / "label.csv"):
        gains[int(row["query_id"])][int(row["product_id"])] = GAIN[row["label"]]
    return [Query(qid, text, dict(gains[qid])) for qid, text in sorted(texts.items())]


def build(data_dir: Path, size: int, eval_count: int) -> tuple[list[Product], list[Query]]:
    products = read_products(data_dir)
    queries = [q for q in read_queries(data_dir) if any(g == 1.0 for g in q.gains.values())]
    rng = random.Random(SEED)
    chosen = sorted(rng.sample(queries, min(eval_count, len(queries))), key=lambda q: q.id)
    size = min(size, len(products))

    exact = sorted({pid for q in chosen for pid, g in q.gains.items() if g == 1.0 and pid in products})
    partial = sorted({pid for q in chosen for pid, g in q.gains.items() if g < 1.0 and pid in products} - set(exact))
    rng.shuffle(partial)
    selected = exact[:size]
    selected += partial[: max(0, int(size * 0.7) - len(selected))]
    taken = set(selected)
    rest = sorted(set(products) - taken)
    rng.shuffle(rest)
    selected += rest[: size - len(selected)]

    catalog = sorted(selected)
    present = set(catalog)
    evaluation = [Query(q.id, q.text, {p: g for p, g in q.gains.items() if p in present}) for q in chosen]
    return [products[pid] for pid in catalog], evaluation
