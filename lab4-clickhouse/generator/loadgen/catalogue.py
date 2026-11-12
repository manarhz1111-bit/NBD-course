from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    method: str
    weight: float
    latency_ms: float
    sigma: float
    bytes_mean: int
    client_error: float = 0.004


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    weight: float
    error_rate: float
    version: str
    endpoints: tuple[Endpoint, ...]
    pods: int = 3


@dataclass(frozen=True, slots=True)
class Region:
    name: str
    weight: float
    extra_ms: float


REGIONS: tuple[Region, ...] = (
    Region("eu-central-1", 0.46, 0.0),
    Region("us-east-1", 0.34, 14.0),
    Region("ap-south-1", 0.20, 38.0),
)

SERVICES: tuple[Service, ...] = (
    Service("frontend", 28, 0.0015, "v2.7.1", (
        Endpoint("GET /", "GET", 34, 38, 0.45, 18_000),
        Endpoint("GET /product/{id}", "GET", 38, 52, 0.50, 24_000),
        Endpoint("POST /cart", "POST", 16, 61, 0.45, 2_400, 0.010),
        Endpoint("POST /cart/checkout", "POST", 6, 240, 0.55, 3_100, 0.015),
        Endpoint("GET /static", "GET", 6, 6, 0.30, 140_000, 0.001),
    )),
    Service("productcatalogservice", 22, 0.0008, "v1.12.0", (
        Endpoint("ListProducts", "POST", 30, 14, 0.40, 9_000),
        Endpoint("GetProduct", "POST", 58, 6, 0.35, 1_200, 0.006),
        Endpoint("SearchProducts", "POST", 12, 85, 0.70, 6_500),
    )),
    Service("currencyservice", 16, 0.0005, "v1.4.9", (
        Endpoint("Convert", "POST", 88, 3, 0.30, 180),
        Endpoint("GetSupportedCurrencies", "POST", 12, 2, 0.25, 420),
    )),
    Service("recommendationservice", 11, 0.0020, "v3.1.0", (
        Endpoint("ListRecommendations", "POST", 100, 72, 0.60, 1_100),
    )),
    Service("cartservice", 9, 0.0012, "v2.0.4", (
        Endpoint("GetCart", "POST", 55, 9, 0.40, 800),
        Endpoint("AddItem", "POST", 38, 14, 0.40, 160, 0.008),
        Endpoint("EmptyCart", "POST", 7, 11, 0.35, 60),
    )),
    Service("adservice", 7, 0.0030, "v1.9.3", (
        Endpoint("GetAds", "POST", 100, 24, 0.55, 2_300),
    )),
    Service("shippingservice", 3, 0.0010, "v1.6.2", (
        Endpoint("GetQuote", "POST", 70, 19, 0.40, 210),
        Endpoint("ShipOrder", "POST", 30, 46, 0.45, 260),
    )),
    Service("checkoutservice", 2, 0.0025, "v2.3.0", (
        Endpoint("PlaceOrder", "POST", 100, 310, 0.50, 1_400, 0.012),
    )),
    Service("paymentservice", 1.2, 0.0040, "v1.8.5", (
        Endpoint("Charge", "POST", 100, 130, 0.65, 240, 0.020),
    )),
    Service("emailservice", 1.0, 0.0015, "v1.2.7", (
        Endpoint("SendOrderConfirmation", "POST", 100, 95, 0.50, 120),
    )),
)

SERVER_ERRORS: tuple[tuple[int, str, float], ...] = (
    (500, "internal error", 0.55),
    (503, "upstream unavailable", 0.30),
    (504, "deadline exceeded", 0.15),
)

CLIENT_ERRORS: tuple[tuple[int, str, float], ...] = (
    (400, "invalid argument", 0.45),
    (404, "not found", 0.40),
    (429, "rate limited", 0.15),
)


@dataclass(slots=True)
class Incident:
    service: str
    until: float
    error_multiplier: float
    latency_multiplier: float
    pod: str | None = None
    rollback_to: str | None = None


@dataclass(slots=True)
class ServiceState:
    service: Service
    version: str
    pods: tuple[str, ...]
    incidents: list[Incident] = field(default_factory=list)
