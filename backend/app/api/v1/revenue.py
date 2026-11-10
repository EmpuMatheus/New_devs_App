from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Any, Dict
import logging

from app.services.cache import get_annual_revenue, get_monthly_revenue
from app.services.reservations import RevenueConfigurationError
from app.core.auth import authenticate_request as get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

YEAR_QUERY = Query(..., ge=1900, le=2100)
MONTH_QUERY = Query(..., ge=1, le=12)


def _tenant_id(user: Any) -> str:
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")
    return tenant_id


def _error_response(exc: Exception, tenant_id: str, property_id: str) -> None:
    if isinstance(exc, RevenueConfigurationError):
        logger.exception("Revenue configuration error for tenant %s property %s", tenant_id, property_id)
        raise HTTPException(status_code=500, detail="Revenue configuration error")
    logger.exception("Revenue lookup failed for tenant %s property %s", tenant_id, property_id)
    raise HTTPException(status_code=503, detail="Revenue service unavailable")


def _monthly_response(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "property_id": data["property_id"],
        "year": data["year"],
        "month": data["month"],
        "timezone": data["timezone"],
        "currency": data["currency"],
        "total_revenue_exact": data["total_revenue_exact"],
        "total_revenue": data["total_revenue"],
        "reservations_count": data["reservations_count"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
    }


@router.get("/revenue/monthly")
async def monthly_revenue(
    property_id: str,
    year: int = YEAR_QUERY,
    month: int = MONTH_QUERY,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:

    tenant_id = _tenant_id(current_user)

    try:
        data = await get_monthly_revenue(property_id, tenant_id, year, month)
    except Exception as exc:
        _error_response(exc, tenant_id, property_id)

    if data is None:
        raise HTTPException(status_code=404, detail="Property not found")

    return _monthly_response(data)


@router.get("/revenue/annual")
async def annual_revenue(
    property_id: str,
    year: int = YEAR_QUERY,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:

    tenant_id = _tenant_id(current_user)

    try:
        data = await get_annual_revenue(property_id, tenant_id, year)
    except Exception as exc:
        _error_response(exc, tenant_id, property_id)

    if data is None:
        raise HTTPException(status_code=404, detail="Property not found")

    return {
        "property_id": data["property_id"],
        "year": data["year"],
        "timezone": data["timezone"],
        "currency": data["currency"],
        "total_revenue_exact": data["total_revenue_exact"],
        "total_revenue": data["total_revenue"],
        "reservations_count": data["reservations_count"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
    }
