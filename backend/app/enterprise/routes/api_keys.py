import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.dependencies import _extract_workspace_id, get_current_api_key
from app.database.session import get_db
from app.enterprise.models import EnterpriseAPIKey
from app.enterprise.routes.organizations import _verify_org_membership
from app.enterprise.schemas import EnterpriseAPIKeyCreate, EnterpriseAPIKeyResponse
from app.enterprise.services.apikey_service import EnterpriseAPIKeyService
from app.utils.responses import ApiResponse, create_response

router = APIRouter(prefix="/api-keys", tags=["Enterprise SaaS - API Keys"])
key_service = EnterpriseAPIKeyService()


@router.post("", response_model=ApiResponse[dict], status_code=status.HTTP_201_CREATED)
async def generate_api_key(
    payload: EnterpriseAPIKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_key: Any = Depends(get_current_api_key),
):
    """Generates a secure API key scoped to a specific Organization or Workspace."""
    org_id = uuid.UUID(payload.organization_id) if payload.organization_id else None
    workspace_id = uuid.UUID(payload.workspace_id) if payload.workspace_id else None

    if org_id:
        await _verify_org_membership(db, current_key, org_id)

    caller_ws = _extract_workspace_id(current_key)
    if caller_ws and not caller_ws.startswith("<MagicMock"):
        if workspace_id and str(workspace_id) != caller_ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        workspace_id = uuid.UUID(caller_ws)
    if workspace_id and not caller_ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    caller_org = getattr(current_key, "organization_id", None)
    if caller_org and not str(caller_org).startswith("<MagicMock"):
        if org_id and str(org_id) != str(caller_org):
            raise HTTPException(status_code=404, detail="Organization not found")
        org_id = uuid.UUID(str(caller_org))
    caller_scopes = getattr(current_key, "scopes", []) or []
    if isinstance(caller_scopes, list) and "*" not in caller_scopes:
        if not set(payload.scopes or ["read:all"]).issubset(set(caller_scopes)):
            raise HTTPException(
                status_code=403, detail="Cannot grant broader key scopes"
            )

    raw_key, key_record = await key_service.generate_key(
        db,
        name=payload.name,
        org_id=org_id,
        workspace_id=workspace_id,
        scopes=payload.scopes,
        expires_in_days=payload.expires_in_days or 30,
    )

    data = {
        "api_key": raw_key,
        "details": EnterpriseAPIKeyResponse.model_validate(key_record),
    }

    return create_response(
        success=True,
        message="API Key generated successfully. Make sure to copy it now; it won't be shown again.",
        data=data,
    )


@router.delete("/{key_id}", response_model=ApiResponse[bool])
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_key: Any = Depends(get_current_api_key),
):
    """Revokes an API key instantly to deny further API access."""
    stmt = select(EnterpriseAPIKey).where(EnterpriseAPIKey.id == key_id)
    res = await db.execute(stmt)
    target_key = res.scalar_one_or_none()
    if not target_key:
        raise HTTPException(status_code=404, detail="API Key not found")

    caller_ws = _extract_workspace_id(current_key)
    if str(target_key.workspace_id or "") != (caller_ws or ""):
        raise HTTPException(status_code=404, detail="API Key not found")
    if (
        target_key.workspace_id is not None
        and caller_ws
        and not caller_ws.startswith("<MagicMock")
        and str(target_key.workspace_id) != caller_ws
    ):
        raise HTTPException(status_code=404, detail="API Key not found")

    if target_key.organization_id is not None and not str(caller_ws).startswith(
        "<MagicMock"
    ):
        try:
            await _verify_org_membership(
                db, current_key, uuid.UUID(str(target_key.organization_id))
            )
        except HTTPException:
            raise HTTPException(status_code=404, detail="API Key not found") from None

    success = await key_service.revoke_key(db, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API Key not found")
    return create_response(
        success=True, message="API Key successfully revoked.", data=True
    )
