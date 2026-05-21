"""
User management and self-service profile routes.
"""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_agent_or_admin
from app.db.models.enums import UserRole, UserStatus
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import MessageOut
from app.schemas.user import (
    CurrentUserResponse,
    UserCreate,
    UserListResponse,
    UserPasswordChangeRequest,
    UserProfileUpdate,
    UserResponse,
    UserUpdate,
)
from app.services.settings_service import SettingsService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


async def _build_current_user_response(db: AsyncSession, user: User) -> CurrentUserResponse:
    settings_service = SettingsService(db)
    settings_obj = await settings_service.get_all_settings()
    
    # Transform profile picture URL to use correct API URL for browser access
    profile_picture_url = user.profile_picture_url
    if profile_picture_url:
        from app.core.config import get_settings
        settings = get_settings()
        
        # Replace Docker hostname with localhost
        if "http://api:" in profile_picture_url:
            profile_picture_url = profile_picture_url.replace("http://api:", f"http://localhost:")
        # Or if it's a relative path, prepend the full API URL
        elif profile_picture_url.startswith("/"):
            profile_picture_url = f"{settings.BACKEND_API_URL}{profile_picture_url}"
    
    payload = {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "role": user.role,
        "status": user.status,
        "can_reply_conversations": user.can_reply_conversations,
        "can_reply_whatsapp": user.can_reply_whatsapp,
        "is_vip": user.is_vip,
        "teams_email": user.teams_email,
        "teams_webhook_url": user.teams_webhook_url,
        "timezone": user.timezone,
        "locale": user.locale,
        "must_change_password": user.must_change_password,
        "profile_completed": user.profile_completed,
        "profile_picture_url": profile_picture_url,
        "profile_completion_required": bool(
            user.role == UserRole.ADMIN and settings_obj["require_admin_profile_completion"]
        ),
        "two_factor_enabled": user.two_factor_enabled,
        "two_factor_auth": bool(settings_obj.get("two_factor_auth", False)),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }
    return CurrentUserResponse.model_validate(payload)


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get current authenticated user's profile."""
    return await _build_current_user_response(db, current_user)


@router.patch("/me", response_model=CurrentUserResponse)
async def update_my_profile(
    payload: UserProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    svc = UserService(db)
    try:
        user = await svc.update_profile(current_user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await _build_current_user_response(db, user)


@router.post("/me/password", response_model=MessageOut)
async def change_my_password(
    payload: UserPasswordChangeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    settings_service = SettingsService(db)
    user_service = UserService(db)
    settings = await settings_service.get_all_settings()

    try:
        user = await user_service.change_password(
            current_user.id,
            payload,
            min_password_length=int(settings["min_password_length"]),
            password_complexity=bool(settings["password_complexity"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return {"message": "Password updated successfully"}


@router.post("/me/profile-picture", response_model=CurrentUserResponse)
async def upload_profile_picture(
    file: Annotated[UploadFile, File()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Upload a profile picture for the current user."""
    svc = UserService(db)
    try:
        user = await svc.upload_profile_picture(current_user.id, file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await _build_current_user_response(db, user)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """Create a new user (admin only)."""
    svc = UserService(db)
    try:
        user = await svc.create_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return user


@router.get("", response_model=UserListResponse)
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_agent_or_admin)],
    role: Optional[UserRole] = Query(None),
    status_filter: Optional[UserStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """List users â€” agents & admins only."""
    from app.core.config import get_settings
    settings = get_settings()
    
    svc = UserService(db)
    users, total = await svc.list_users(role=role, status=status_filter, skip=skip, limit=limit)
    
    # Transform profile picture URLs for browser access
    for user in users:
        if user.profile_picture_url:
            if "http://api:" in user.profile_picture_url:
                user.profile_picture_url = user.profile_picture_url.replace("http://api:", f"http://localhost:")
            elif user.profile_picture_url.startswith("/"):
                user.profile_picture_url = f"{settings.BACKEND_API_URL}{user.profile_picture_url}"
    
    return {"users": users, "total": total}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_agent_or_admin)],
):
    """Get user by ID â€” agents & admins only."""
    svc = UserService(db)
    user = await svc.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """Update user â€” admin only."""
    svc = UserService(db)
    try:
        user = await svc.update_user(user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.delete("/{user_id}", response_model=MessageOut)
async def delete_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """Soft-delete user â€” admin only."""
    svc = UserService(db)
    deleted = await svc.soft_delete(user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"message": "User deleted"}
