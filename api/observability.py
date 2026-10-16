"""Request metrics (Prometheus text format) and a small per-client rate limiter. In-process, no extra deps."""
import threading
import time
from collections import defaultdict

_lock = threading.Lock()
BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
_requests: dict[tuple[str, str, int], int] = defaultdict(int)          # (method, route, status) -> count
_latency: dict[str, list[int]] = defaultdict(lambda: [0] * (len(BUCKETS_MS) + 1))
_latency_sum: dict[str, float] = defaultdict(float)


def observe(method: str, route: str, status: int, ms: float) -> None:
    with _lock:
        _requests[(method, route, status)] += 1
        b = _latency[route]
        for i, edge in enumerate(BUCKETS_MS):
            if ms <= edge:
                b[i] += 1
                break
        else:
            b[-1] += 1
        _latency_sum[route] += ms


def render(extra: dict[str, float]) -> str:
    """Prometheus exposition format."""
    out = ["# HELP drift_http_requests_total HTTP requests by route and status",
           "# TYPE drift_http_requests_total counter"]
    with _lock:
        for (m, r, s), n in sorted(_requests.items()):
            out.append(f'drift_http_requests_total{{method="{m}",route="{r}",status="{s}"}} {n}')
        out += ["# HELP drift_http_request_ms Request latency in milliseconds", "# TYPE drift_http_request_ms histogram"]
        for r, b in sorted(_latency.items()):
            acc = 0
            for edge, n in zip(BUCKETS_MS, b):
                acc += n
                out.append(f'drift_http_request_ms_bucket{{route="{r}",le="{edge}"}} {acc}')
            acc += b[-1]
            out.append(f'drift_http_request_ms_bucket{{route="{r}",le="+Inf"}} {acc}')
            out.append(f'drift_http_request_ms_sum{{route="{r}"}} {_latency_sum[r]:.1f}')
            out.append(f'drift_http_request_ms_count{{route="{r}"}} {acc}')
    for name, value in extra.items():
        out.append(f"{name} {value}")
    return "\n".join(out) + "\n"


class RateLimiter:
    """Token bucket per (client, key): `rate` requests per `per` seconds, bursting up to `rate`."""

    def __init__(self, rate: int = 20, per: float = 60.0):
        self.rate, self.per = rate, per
        self._b: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._b.get((client, key), (float(self.rate), now))
            tokens = min(float(self.rate), tokens + (now - last) * self.rate / self.per)
            if tokens < 1:
                self._b[(client, key)] = (tokens, now)
                return False
            self._b[(client, key)] = (tokens - 1, now)
            return True
