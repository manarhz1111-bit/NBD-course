from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .simulator import DEPLOYMENT_COLUMNS, REQUEST_COLUMNS, Simulator
from .sink import Sink, connect

log = logging.getLogger("loadgen")
stop = threading.Event()


def _empty(columns):
    return {c: [] for c in columns}


def _extend(target, source):
    for column, values in source.items():
        target[column].extend(values)


def _size(data):
    return len(next(iter(data.values())))


def backfill(args) -> None:
    sim, sink = Simulator(args.seed), Sink()
    end = time.time()
    t = (end - args.hours * 3_600) // 60 * 60
    requests, deployments = _empty(REQUEST_COLUMNS), _empty(DEPLOYMENT_COLUMNS)
    total, started = 0, time.monotonic()
    while t < end and not stop.is_set():
        r, d = sim.window(t, min(t + 60, end), args.rate)
        _extend(requests, r)
        _extend(deployments, d)
        t += 60
        if _size(requests) >= args.batch:
            total += sink.requests(requests)
            requests = _empty(REQUEST_COLUMNS)
            log.info("backfill: %d rows, simulated up to %s", total, time.strftime("%Y-%m-%d %H:%M", time.gmtime(t)))
    total += sink.requests(requests)
    deploys = sink.deployments(deployments)
    elapsed = time.monotonic() - started
    log.info("backfill done: %d requests, %d deployment events, %.1fs, %.0f rows/s", total, deploys, elapsed, total / max(elapsed, 1e-9))


def stream(args) -> None:
    sim, sink = Simulator(args.seed), Sink()
    last, report_at, rows, batches = time.time(), time.monotonic() + 60, 0, 0
    log.info("stream: %.1f req/s on average, one batch every %.1fs", args.rate, args.interval)
    while not stop.wait(args.interval):
        now = time.time()
        r, d = sim.window(last, now, args.rate)
        rows += sink.requests(r)
        sink.deployments(d)
        batches += 1
        last = now
        if time.monotonic() >= report_at:
            log.info("stream: %d rows in %d batches during the last minute", rows, batches)
            report_at, rows, batches = time.monotonic() + 60, 0, 0


def _rows(sim: Simulator, count: int):
    data = _empty(REQUEST_COLUMNS)
    t = time.time() - 60
    while _size(data) < count:
        r, _ = sim.window(t, t + 60, count / 30)
        _extend(data, r)
    return {c: v[:count] for c, v in data.items()}


def inserts(args) -> None:
    data = _rows(Simulator(args.seed), args.rows)
    started = time.monotonic()
    if args.mode == "batch":
        Sink().requests(data, table=args.table)
        statements = 1
    else:
        settings = {"async_insert": 1, "wait_for_async_insert": 1} if args.mode == "async" else {"async_insert": 0}
        singles = [{c: [v[i]] for c, v in data.items()} for i in range(args.rows)]

        def worker(part):
            sink = Sink(connect())
            for row in part:
                sink.requests(row, table=args.table, settings=settings)
            return len(part)

        chunks = [singles[i::args.workers] for i in range(args.workers)]
        with ThreadPoolExecutor(args.workers) as pool:
            statements = sum(pool.map(worker, chunks))
    print(json.dumps({
        "mode": args.mode,
        "table": args.table,
        "rows": args.rows,
        "insert_statements": statements,
        "seconds": round(time.monotonic() - started, 2),
    }))


def main() -> None:
    parser = argparse.ArgumentParser(prog="loadgen")
    parser.add_argument("--seed", type=int, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backfill")
    p.add_argument("--hours", type=float, default=48)
    p.add_argument("--rate", type=float, default=40)
    p.add_argument("--batch", type=int, default=200_000)
    p.set_defaults(func=backfill)

    p = sub.add_parser("stream")
    p.add_argument("--rate", type=float, default=40)
    p.add_argument("--interval", type=float, default=5)
    p.set_defaults(func=stream)

    p = sub.add_parser("inserts")
    p.add_argument("--table", default="insert_lab")
    p.add_argument("--rows", type=int, default=300)
    p.add_argument("--mode", choices=("single", "async", "batch"), default="single")
    p.add_argument("--workers", type=int, default=20)
    p.set_defaults(func=inserts)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    args.func(args)


if __name__ == "__main__":
    main()
