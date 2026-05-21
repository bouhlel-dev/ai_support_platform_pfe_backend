"""
User-related request / response schemas.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.db.models.enums import UserRole, UserStatus


# ── Request schemas ───────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: UserRole = UserRole.CLIENT
    phone_number: Optional[str] = Field(None, min_length=8, max_length=20)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None
    phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    can_reply_conversations: Optional[bool] = None
    can_reply_whatsapp: Optional[bool] = None
    is_vip: Optional[bool] = None
    teams_email: Optional[EmailStr] = None
    teams_webhook_url: Optional[str] = Field(None, max_length=1000)
    timezone: Optional[str] = Field(None, max_length=64)
    locale: Optional[str] = Field(None, max_length=16)
    must_change_password: Optional[bool] = None
    profile_completed: Optional[bool] = None
    two_factor_enabled: Optional[bool] = None
    totp_secret: Optional[str] = Field(None, max_length=32)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ── Response schemas ──────────────────────────────

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone_number: Optional[str] = None
    role: UserRole
    status: UserStatus
    can_reply_conversations: bool
    can_reply_whatsapp: bool
    is_vip: bool = False
    two_factor_enabled: bool = False
    profile_picture_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone_number: Optional[str] = None
    role: UserRole
    status: UserStatus
    can_reply_conversations: bool
    can_reply_whatsapp: bool
    is_vip: bool = False
    two_factor_enabled: bool = False
    two_factor_auth: bool = False
    teams_email: Optional[str] = None
    teams_webhook_url: Optional[str] = None
    timezone: str
    locale: str
    must_change_password: bool
    profile_completed: bool
    profile_completion_required: bool
    profile_picture_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    teams_email: Optional[EmailStr] = None
    teams_webhook_url: Optional[str] = Field(None, max_length=1000)
    timezone: Optional[str] = Field(None, max_length=64)
    locale: Optional[str] = Field(None, max_length=16)


class UserPasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
