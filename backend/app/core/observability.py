import logging
from collections import defaultdict
from time import perf_counter
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


logger = logging.getLogger(__name__)


class RequestMetrics:
    """Small in-process request metrics useful for local diagnostics."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "requests": 0,
                "errors": 0,
                "total_ms": 0,
                "max_ms": 0,
            }
        )

    @staticmethod
    def route_name(request: Request) -> str:
        route = request.scope.get("route")
        return str(getattr(route, "path", request.url.path))

    def record(
        self,
        *,
        route: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        value = self._values[route]
        value["requests"] += 1
        value["total_ms"] += duration_ms
        value["max_ms"] = max(value["max_ms"], duration_ms)
        if status_code >= 500:
            value["errors"] += 1

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "route": route,
                "requests": int(value["requests"]),
                "errors": int(value["errors"]),
                "avg_ms": round(
                    value["total_ms"] / value["requests"],
                    2,
                )
                if value["requests"]
                else 0,
                "max_ms": round(value["max_ms"], 2),
            }
            for route, value in sorted(self._values.items())
        ]


request_metrics = RequestMetrics()


async def observe_request(
    request: Request,
    call_next,
) -> Response:
    started_at = perf_counter()
    response: Response | None = None
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        raise
    finally:
        duration_ms = (perf_counter() - started_at) * 1000
        route = request_metrics.route_name(request)
        request_metrics.record(
            route=route,
            status_code=status_code,
            duration_ms=duration_ms,
        )

        if duration_ms >= settings.observability_slow_request_ms:
            logger.warning(
                "慢请求 route=%s method=%s status=%s duration_ms=%.2f",
                route,
                request.method,
                status_code,
                duration_ms,
            )

        if response is not None:
            response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
