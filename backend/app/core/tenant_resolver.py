"""
Minimal tenant resolver for authentication.

Resolution order:
1. Tenant claim from a verified token payload (root or app_metadata only).
2. Explicit assignment-account mapping.
3. No tenant (fail closed).
"""
import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)

TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _valid_tenant_id(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    tenant_id = value.strip()
    if not tenant_id or not TENANT_ID_PATTERN.match(tenant_id):
        return None
    return tenant_id


class TenantResolver:
    """Resolve tenant context from trusted claims or explicit account mappings."""

    @staticmethod
    def resolve_tenant_from_token(token_payload: Optional[dict]) -> Optional[str]:
        """Extract tenant_id from a verified JWT payload.

        Only the root claim and app_metadata are trusted. user_metadata is
        user-editable and is intentionally ignored.
        """
        if not isinstance(token_payload, dict):
            return None

        claim = _valid_tenant_id(token_payload.get("tenant_id"))
        if claim:
            return claim

        app_metadata = token_payload.get("app_metadata")
        if isinstance(app_metadata, dict):
            claim = _valid_tenant_id(app_metadata.get("tenant_id"))
            if claim:
                return claim

        logger.warning("No trusted tenant_id found in token payload")
        return None

    @staticmethod
    def resolve_tenant_from_user(user_data: dict) -> Optional[str]:
        """Extract tenant_id from trusted user data (root/app_metadata only)."""
        if not isinstance(user_data, dict):
            return None

        claim = _valid_tenant_id(user_data.get("tenant_id"))
        if claim:
            return claim

        app_metadata = user_data.get("app_metadata")
        if isinstance(app_metadata, dict):
            claim = _valid_tenant_id(app_metadata.get("tenant_id"))
            if claim:
                return claim

        return None

    @staticmethod
    async def resolve_tenant_id(
        user_id: str,
        user_email: str,
        token: Optional[str] = None,
        token_payload: Optional[dict] = None,
    ) -> Optional[str]:
        """Resolve tenant for a user, failing closed when no trusted source exists."""
        claim = TenantResolver.resolve_tenant_from_token(token_payload)
        if claim:
            return claim

        # Explicit challenge-account mappings.
        if user_email == "sunset@propertyflow.com":
            return "tenant-a"
        if user_email == "ocean@propertyflow.com":
            return "tenant-b"
        if user_email == "candidate@propertyflow.com":
            return "tenant-a"

        logger.warning("No tenant mapping found for user %s", user_email)
        return None

    @staticmethod
    async def update_user_tenant_metadata(user_id: str, tenant_id: str) -> None:
        """No-op placeholder retained for compatibility."""
        pass
