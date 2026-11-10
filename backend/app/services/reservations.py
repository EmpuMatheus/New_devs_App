from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database_pool import db_pool

EXACT_SCALE = Decimal("0.001")
DISPLAY_SCALE = Decimal("0.01")


class RevenueConfigurationError(Exception):
    """Raised for invalid property revenue configuration (timezone/currency)."""


def get_timezone(timezone_name: Optional[str]) -> ZoneInfo:
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise RevenueConfigurationError("Property has no valid timezone")
    try:
        return ZoneInfo(timezone_name)
    except Exception as exc:
        raise RevenueConfigurationError(
            f"Invalid property timezone: {timezone_name!r}"
        ) from exc


def month_bounds_utc(year: int, month: int, timezone_name: str) -> Tuple[datetime, datetime]:
    """Return the half-open UTC interval for a local calendar month."""
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    tz = get_timezone(timezone_name)
    start_local = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=tz)

    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def year_bounds_utc(year: int, timezone_name: str) -> Tuple[datetime, datetime]:
    """Return the half-open UTC interval for a local calendar year."""
    tz = get_timezone(timezone_name)
    start_local = datetime(year, 1, 1, tzinfo=tz)
    end_local = datetime(year + 1, 1, 1, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def format_amounts(total: Decimal) -> Tuple[str, str]:
    """Return (exact 3dp string, display 2dp string rounded HALF_UP)."""
    exact = total.quantize(EXACT_SCALE, rounding=ROUND_HALF_UP)
    display = total.quantize(DISPLAY_SCALE, rounding=ROUND_HALF_UP)
    return str(exact), str(display)


async def _load_property_context(property_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    if not db_pool.session_factory:
        await db_pool.initialize()

    query = text("""
        SELECT
            p.timezone,
            COUNT(DISTINCT r.currency) AS currency_count,
            MIN(r.currency) AS currency
        FROM properties p
        LEFT JOIN reservations r
            ON r.property_id = p.id AND r.tenant_id = p.tenant_id
        WHERE p.id = :property_id AND p.tenant_id = :tenant_id
        GROUP BY p.id, p.timezone
    """)

    async with db_pool.get_session() as session:
        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
        })
        row = result.fetchone()

    if not row:
        return None

    if (row.currency_count or 0) > 1:
        raise RevenueConfigurationError(
            f"Property {property_id} has reservations in multiple currencies"
        )

    return {
        "timezone": row.timezone,
        "currency": row.currency or "USD",
    }


async def _sum_period(
    property_id: str,
    tenant_id: str,
    currency: str,
    start_utc: Optional[datetime],
    end_utc: Optional[datetime],
) -> Tuple[Decimal, int]:
    sql = """
        SELECT
            COALESCE(SUM(total_amount), 0) AS total_revenue,
            COUNT(*) AS reservation_count
        FROM reservations
        WHERE property_id = :property_id
          AND tenant_id = :tenant_id
          AND COALESCE(currency, 'USD') = :currency
    """
    params: Dict[str, Any] = {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "currency": currency,
    }

    if start_utc is not None:
        sql += " AND check_in_date >= :start_utc"
        params["start_utc"] = start_utc
    if end_utc is not None:
        sql += " AND check_in_date < :end_utc"
        params["end_utc"] = end_utc

    async with db_pool.get_session() as session:
        result = await session.execute(text(sql), params)
        row = result.fetchone()

    return Decimal(str(row.total_revenue)), int(row.reservation_count)


async def _build_result(
    property_id: str,
    tenant_id: str,
    context: Dict[str, Any],
    start_utc: Optional[datetime],
    end_utc: Optional[datetime],
) -> Dict[str, Any]:
    total, count = await _sum_period(
        property_id, tenant_id, context["currency"], start_utc, end_utc
    )
    exact, display = format_amounts(total)

    result: Dict[str, Any] = {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "timezone": context["timezone"],
        "currency": context["currency"],
        "total_revenue_exact": exact,
        "total_revenue": display,
        "reservations_count": count,
    }
    if start_utc is not None:
        result["period_start"] = start_utc.isoformat()
    if end_utc is not None:
        result["period_end"] = end_utc.isoformat()
    return result


async def calculate_revenue_for_period(
    property_id: str,
    tenant_id: str,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Aggregate revenue for a tenant-owned property over an optional UTC interval."""
    context = await _load_property_context(property_id, tenant_id)
    if context is None:
        return None
    return await _build_result(property_id, tenant_id, context, start_utc, end_utc)


async def calculate_total_revenue(
    property_id: str, tenant_id: str
) -> Optional[Dict[str, Any]]:
    """All-time revenue for a tenant-owned property."""
    return await calculate_revenue_for_period(property_id, tenant_id)


async def calculate_monthly_revenue(
    property_id: str, tenant_id: str, year: int, month: int
) -> Optional[Dict[str, Any]]:
    """Revenue for the property-local calendar month."""
    context = await _load_property_context(property_id, tenant_id)
    if context is None:
        return None

    start_utc, end_utc = month_bounds_utc(year, month, context["timezone"])
    result = await _build_result(property_id, tenant_id, context, start_utc, end_utc)
    result["year"] = year
    result["month"] = month
    return result


async def calculate_annual_revenue(
    property_id: str, tenant_id: str, year: int
) -> Optional[Dict[str, Any]]:
    """Revenue for the property-local calendar year."""
    context = await _load_property_context(property_id, tenant_id)
    if context is None:
        return None

    start_utc, end_utc = year_bounds_utc(year, context["timezone"])
    result = await _build_result(property_id, tenant_id, context, start_utc, end_utc)
    result["year"] = year
    return result
