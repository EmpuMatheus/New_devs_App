import json
import os
from typing import Any, Awaitable, Callable, Dict, Optional

import redis.asyncio as redis

redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

CACHE_TTL = 300


def _cache_key(property_id: str, tenant_id: str, period: str = "all") -> str:
    return f"revenue:v2:{tenant_id}:{property_id}:{period}"


async def _cached(
    key: str, calculate: Callable[[], Awaitable[Optional[Dict[str, Any]]]]
) -> Optional[Dict[str, Any]]:
    cached = await redis_client.get(key)
    if cached:
        return json.loads(cached)

    result = await calculate()
    if result is None:
        return None

    await redis_client.setex(key, CACHE_TTL, json.dumps(result))
    return result


async def get_revenue_summary(
    property_id: str, tenant_id: str
) -> Optional[Dict[str, Any]]:
    from app.services.reservations import calculate_total_revenue

    return await _cached(
        _cache_key(property_id, tenant_id, "all"),
        lambda: calculate_total_revenue(property_id, tenant_id),
    )


async def get_monthly_revenue(
    property_id: str, tenant_id: str, year: int, month: int
) -> Optional[Dict[str, Any]]:
    from app.services.reservations import calculate_monthly_revenue

    return await _cached(
        _cache_key(property_id, tenant_id, f"month:{year:04d}-{month:02d}"),
        lambda: calculate_monthly_revenue(property_id, tenant_id, year, month),
    )


async def get_annual_revenue(
    property_id: str, tenant_id: str, year: int
) -> Optional[Dict[str, Any]]:
    from app.services.reservations import calculate_annual_revenue

    return await _cached(
        _cache_key(property_id, tenant_id, f"year:{year:04d}"),
        lambda: calculate_annual_revenue(property_id, tenant_id, year),
    )
