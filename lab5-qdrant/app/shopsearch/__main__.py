from __future__ import annotations

import argparse
import json
import sys

from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shopsearch")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("warmup")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--recreate", action="store_true")
    commands.add_parser("eval")
    load = commands.add_parser("loadtest")
    load.add_argument("--duration", type=float, default=15.0)
    load.add_argument("--levels", type=lambda s: [int(x) for x in s.split(",")], default=[1, 2, 4, 8, 16])
    bench = commands.add_parser("bench")
    bench.add_argument("--points", type=int, default=100_000)
    ask = commands.add_parser("ask")
    ask.add_argument("query")
    ask.add_argument("--mode", choices=["dense", "sparse", "hybrid"], default="hybrid")
    ask.add_argument("--limit", type=int, default=5)
    ask.add_argument("--category")
    ask.add_argument("--min-rating", type=float)
    args = parser.parse_args(argv)
    settings = Settings()

    if args.command == "warmup":
        from .pipeline import warmup
        print(json.dumps(warmup(settings), ensure_ascii=False))
    elif args.command == "ingest":
        from .pipeline import ingest
        print(json.dumps(ingest(settings, recreate=args.recreate), ensure_ascii=False))
    elif args.command == "eval":
        from .evaluate import run
        print("\n".join(run(settings)["lines"]))
    elif args.command == "loadtest":
        from .loadtest import run
        print("\n".join(run(settings, duration=args.duration, levels=args.levels)))
    elif args.command == "bench":
        from .bench import run
        print("\n".join(run(settings, n=args.points)))
    elif args.command == "ask":
        from . import store
        from .encoder import Encoder
        encoder = Encoder(settings)
        client = store.connect(settings.qdrant_url, settings.qdrant_api_key)
        points = store.search(client, settings.collection, args.mode,
                              encoder.dense_query(args.query), encoder.sparse_query(args.query), limit=args.limit,
                              category=args.category, min_rating=args.min_rating)
        for rank, p in enumerate(points, start=1):
            rating = p.payload.get("rating")
            print(f"{rank}. [{p.score:.4f}] {p.payload['name']} | {p.payload['category']} / {p.payload['product_class']}"
                  f" | rating {rating if rating is not None else '-'} ({p.payload.get('reviews', 0)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
