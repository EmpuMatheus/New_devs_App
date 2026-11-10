from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List
import logging

from sqlalchemy import text

from app.core.auth import authenticate_request as get_current_user
from app.core.database_pool import db_pool

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/properties")
async def list_properties(
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:

    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context")

    try:
        if not db_pool.session_factory:
            await db_pool.initialize()

        async with db_pool.get_session() as session:
            result = await session.execute(
                text("""
                    SELECT id, name, timezone
                    FROM properties
                    WHERE tenant_id = :tenant_id
                    ORDER BY id
                """),
                {"tenant_id": tenant_id}
            )
            rows = result.mappings().all()
    except Exception:
        logger.exception("Property lookup failed for tenant %s", tenant_id)
        raise HTTPException(status_code=503, detail="Property service unavailable")

    items: List[Dict[str, Any]] = [
        {"id": row["id"], "name": row["name"], "timezone": row["timezone"]}
        for row in rows
    ]
    return {"items": items, "total": len(items)}