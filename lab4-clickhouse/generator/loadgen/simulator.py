from __future__ import annotations

import math
import random
import uuid
from bisect import bisect
from datetime import datetime, timezone
from itertools import accumulate

from .catalogue import CLIENT_ERRORS, REGIONS, SERVER_ERRORS, SERVICES, Incident, ServiceState

REQUEST_COLUMNS = (
    "ts", "service", "endpoint", "method", "status", "duration_ms", "bytes_sent",
    "region", "pod", "version", "user_id", "trace_id", "error",
)
DEPLOYMENT_COLUMNS = ("ts", "service", "version", "kind")

DEPLOYS_PER_DAY = 2.4
BAD_DEPLOY_SHARE = 0.35
POD_DEGRADATIONS_PER_DAY = 1.0
USERS = 60_000


def _cumulative(weights):
    return list(accumulate(weights))


def _pick(cum, rnd):
    return bisect(cum, rnd * cum[-1])


def _bump(version: str) -> str:
    major, minor, patch = version.lstrip("v").split(".")
    return f"v{major}.{minor}.{int(patch) + 1}"


def traffic_factor(ts: float) -> float:
    hour = (ts % 86_400) / 3_600
    return max(0.2, 0.62 + 0.38 * math.sin(2 * math.pi * (hour - 8) / 24))


class Simulator:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.states = [
            ServiceState(svc, svc.version, tuple(f"{svc.name}-{self.rng.randrange(16**5):05x}" for _ in range(svc.pods)))
            for svc in SERVICES
        ]
        self.service_cum = _cumulative(s.weight for s in SERVICES)
        self.endpoint_cum = [_cumulative(e.weight for e in s.endpoints) for s in SERVICES]
        self.region_cum = _cumulative(r.weight for r in REGIONS)
        self.server_cum = _cumulative(e[2] for e in SERVER_ERRORS)
        self.client_cum = _cumulative(e[2] for e in CLIENT_ERRORS)

    def _chaos(self, start: float, end: float, deployments: dict[str, list]) -> None:
        rng = self.rng
        minutes = (end - start) / 60
        p_deploy = DEPLOYS_PER_DAY / 1_440 * minutes
        p_pod = POD_DEGRADATIONS_PER_DAY / 1_440 * minutes
        for state in self.states:
            for incident in [i for i in state.incidents if i.until <= start]:
                state.incidents.remove(incident)
                if incident.rollback_to:
                    state.version = incident.rollback_to
                    self._record(deployments, incident.until, state, "rollback")
            busy = any(i.rollback_to for i in state.incidents)
            if not busy and rng.random() < p_deploy:
                at = rng.uniform(start, end)
                previous, state.version = state.version, _bump(state.version)
                self._record(deployments, at, state, "deploy")
                if rng.random() < BAD_DEPLOY_SHARE:
                    state.incidents.append(Incident(
                        state.service.name, at + rng.uniform(6, 25) * 60,
                        rng.uniform(12, 30), rng.uniform(1.8, 3.5), None, previous,
                    ))
            if rng.random() < p_pod:
                state.incidents.append(Incident(
                    state.service.name, start + rng.uniform(8, 30) * 60,
                    rng.uniform(2, 4), rng.uniform(3, 5), rng.choice(state.pods),
                ))

    @staticmethod
    def _record(deployments: dict[str, list], at: float, state: ServiceState, kind: str) -> None:
        deployments["ts"].append(datetime.fromtimestamp(at, timezone.utc).replace(microsecond=0))
        deployments["service"].append(state.service.name)
        deployments["version"].append(state.version)
        deployments["kind"].append(kind)

    def window(self, start: float, end: float, rate: float) -> tuple[dict[str, list], dict[str, list]]:
        rng = self.rng
        requests = {c: [] for c in REQUEST_COLUMNS}
        deployments = {c: [] for c in DEPLOYMENT_COLUMNS}
        self._chaos(start, end, deployments)

        expected = rate * traffic_factor(start) * (end - start)
        count = max(0, round(rng.gauss(expected, math.sqrt(expected)))) if expected > 0 else 0

        shared = []
        for state in self.states:
            err, lat, per_pod = 1.0, 1.0, {}
            for incident in state.incidents:
                if incident.pod is None:
                    err *= incident.error_multiplier
                    lat *= incident.latency_multiplier
                else:
                    pe, pl = per_pod.get(incident.pod, (1.0, 1.0))
                    per_pod[incident.pod] = (pe * incident.error_multiplier, pl * incident.latency_multiplier)
            shared.append((err, lat, per_pod))

        span = end - start
        for _ in range(count):
            si = _pick(self.service_cum, rng.random())
            state = self.states[si]
            svc = state.service
            ep = svc.endpoints[_pick(self.endpoint_cum[si], rng.random())]
            region = REGIONS[_pick(self.region_cum, rng.random())]
            pod = state.pods[rng.randrange(len(state.pods))]

            err, lat, per_pod = shared[si]
            if pod in per_pod:
                pe, pl = per_pod[pod]
                err, lat = err * pe, lat * pl

            duration = rng.lognormvariate(math.log(ep.latency_ms), ep.sigma) * lat + region.extra_ms * rng.uniform(0.6, 1.4)
            roll = rng.random()
            server_p = min(0.9, svc.error_rate * err)
            if roll < server_p:
                status, error, _ = SERVER_ERRORS[_pick(self.server_cum, rng.random())]
                if status == 504:
                    duration = max(duration, rng.uniform(1_000, 1_200))
                size = rng.randint(60, 240)
            elif roll < server_p + ep.client_error:
                status, error, _ = CLIENT_ERRORS[_pick(self.client_cum, rng.random())]
                duration *= 0.3
                size = rng.randint(60, 240)
            else:
                status, error = 200, ""
                size = int(rng.expovariate(1 / ep.bytes_mean)) + 40

            ts = start + rng.random() * span
            requests["ts"].append(datetime.fromtimestamp(ts, timezone.utc))
            requests["service"].append(svc.name)
            requests["endpoint"].append(ep.name)
            requests["method"].append(ep.method)
            requests["status"].append(status)
            requests["duration_ms"].append(round(duration, 3))
            requests["bytes_sent"].append(size)
            requests["region"].append(region.name)
            requests["pod"].append(pod)
            requests["version"].append(state.version)
            requests["user_id"].append(min(USERS, int(rng.paretovariate(1.15) * 40)))
            requests["trace_id"].append(uuid.UUID(int=rng.getrandbits(128)))
            requests["error"].append(error)
        return requests, deployments
