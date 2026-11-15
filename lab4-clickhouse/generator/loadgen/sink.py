from __future__ import annotations

import logging
import os
import time

import clickhouse_connect
from clickhouse_connect.driver.exceptions import OperationalError

from .simulator import DEPLOYMENT_COLUMNS, REQUEST_COLUMNS

log = logging.getLogger("loadgen.sink")

DIRECT_INSERT = {"async_insert": 0}


def connect():
    return clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "127.0.0.1"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ["CH_USER"],
        password=os.environ["CH_PASSWORD"],
        database=os.environ.get("CH_DATABASE", "lab4"),
        compress="lz4",
        autogenerate_session_id=False,
        send_receive_timeout=120,
    )


class Sink:
    def __init__(self, client=None, retries: int = 5):
        self.client = client or connect()
        self.retries = retries

    def _insert(self, table: str, columns: tuple[str, ...], data: dict[str, list], settings=None) -> int:
        rows = len(data[columns[0]])
        if not rows:
            return 0
        payload = [data[c] for c in columns]
        settings = settings or DIRECT_INSERT
        for attempt in range(1, self.retries + 1):
            try:
                self.client.insert(table, payload, column_names=list(columns), column_oriented=True, settings=settings)
                return rows
            except OperationalError as exc:
                if attempt == self.retries:
                    raise
                delay = min(30, 2 ** attempt)
                log.warning("insert into %s failed (%s), retry %d in %ds", table, exc.__class__.__name__, attempt, delay)
                time.sleep(delay)
        return 0

    def requests(self, data: dict[str, list], table: str = "requests", settings=None) -> int:
        return self._insert(table, REQUEST_COLUMNS, data, settings)

    def deployments(self, data: dict[str, list]) -> int:
        return self._insert("deployments", DEPLOYMENT_COLUMNS, data)
