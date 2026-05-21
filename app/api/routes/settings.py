"""
Persisted admin settings routes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models.enums import AuditAction
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.settings import (
    AdminSettingsResponse,
    AutomationSettingsUpdate,
    BrandingSettingsUpdate,
    GeneralSettingsUpdate,
    NotificationSettingsUpdate,
    PublicAuthSettingsResponse,
    SecuritySettingsUpdate,
    SmsTestRequest,
    TicketSettingsUpdate,
)
from app.services.audit_service import AuditService
from app.services.settings_service import SettingsService
from app.services.sms_service import SmsService

router = APIRouter(prefix="/settings", tags=["Settings"])


async def _update_section(
    *,
    section: str,
    payload: dict,
    request: Request,
    db: AsyncSession,
    current_user: User,
) -> AdminSettingsResponse:
    settings_service = SettingsService(db)
    audit = AuditService(db)

    try:
        settings = await settings_service.update_section(section, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.log(
        action=AuditAction.UPDATE,
        resource_type="settings",
        resource_id=section,
        user_id=current_user.id,
        description=f"Updated {section} settings",
        meta={"section": section, "keys": sorted(payload.keys())},
        trace_id=request.state.trace_id if hasattr(request.state, "trace_id") else None,
        ip_address=request.client.host if request.client else None,
    )
    return AdminSettingsResponse.model_validate(settings)


@router.get("", response_model=AdminSettingsResponse)
async def get_admin_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    service = SettingsService(db)
    return AdminSettingsResponse.model_validate(await service.get_all_settings())


@router.get("/public", response_model=PublicAuthSettingsResponse)
async def get_public_auth_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SettingsService(db)
    settings = await service.get_all_settings()
    public_payload = {
        "app_name": settings["app_name"],
        "description": settings["description"],
        "allow_registration": settings["allow_registration"],
        "min_password_length": settings["min_password_length"],
        "password_complexity": settings["password_complexity"],
    }
    return PublicAuthSettingsResponse.model_validate(public_payload)


@router.put("/general", response_model=AdminSettingsResponse)
async def update_general_settings(
    payload: GeneralSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    return await _update_section(
        section="general",
        payload=payload.model_dump(),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.put("/branding", response_model=AdminSettingsResponse)
async def update_branding_settings(
    payload: BrandingSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    return await _update_section(
        section="branding",
        payload=payload.model_dump(),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.put("/tickets", response_model=AdminSettingsResponse)
async def update_ticket_settings(
    payload: TicketSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    return await _update_section(
        section="tickets",
        payload=payload.model_dump(),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.put("/security", response_model=AdminSettingsResponse)
async def update_security_settings(
    payload: SecuritySettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    return await _update_section(
        section="security",
        payload=payload.model_dump(),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.put("/notifications", response_model=AdminSettingsResponse)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    return await _update_section(
        section="notifications",
        payload=payload.model_dump(),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.put("/automation", response_model=AdminSettingsResponse)
async def update_automation_settings(
    payload: AutomationSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    return await _update_section(
        section="automation",
        payload=payload.model_dump(),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/sms/test")
async def test_sms(
    payload: SmsTestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    settings_service = SettingsService(db)
    sms_service = SmsService(settings_service)
    config = await sms_service._get_config()
    if not sms_service.is_configured(config):
        return {"success": False, "message": "SMS not configured — set API URL and key first."}
    return await sms_service.test_connection(payload.phone, payload.message)
