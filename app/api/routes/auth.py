"""
Authentication routes — login, register, refresh, logout, 2FA.
"""

import secrets
from typing import Annotated

import pyotp
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.enums import AuditAction
from app.api.deps import get_redis, get_current_user, RedisService
from app.schemas.auth import (
    TokenPair,
    TokenRefreshRequest,
    VerifyOtpRequest,
    SetupTwoFactorResponse,
    VerifyTwoFactorSetupRequest,
    DisableTwoFactorRequest,
)
from app.schemas.user import UserLogin, UserCreate, UserResponse, CurrentUserResponse
from app.schemas.common import MessageOut
from app.services.auth_service import AuthService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.db.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── In-memory temporary token store ──────────────────────────
# Maps temp_token -> { user_id, expires_at }
_pending_2fa: dict[str, dict] = {}


def _generate_temp_token() -> str:
    return secrets.token_urlsafe(32)


def _clean_expired_temp_tokens():
    import time
    expired = [k for k, v in _pending_2fa.items() if v.get("expires_at", 0) < time.time()]
    for k in expired:
        _pending_2fa.pop(k, None)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a new user account."""
    user_service = UserService(db)
    settings_service = SettingsService(db)
    settings = await settings_service.get_all_settings()

    if not settings["allow_registration"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "registration_disabled",
                "message": "Registration is currently disabled by an administrator.",
            },
        )

    try:
        user_service.validate_password_policy(
            payload.password,
            min_password_length=int(settings["min_password_length"]),
            password_complexity=bool(settings["password_complexity"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        user = await user_service.create_user(payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    # Audit
    audit = AuditService(db)
    await audit.log(
        action=AuditAction.CREATE,
        resource_type="user",
        resource_id=str(user.id),
        user_id=user.id,
        description=f"User registered: {user.email}",
        trace_id=request.state.trace_id if hasattr(request.state, "trace_id") else None,
        ip_address=request.client.host if request.client else None,
    )
    return user


@router.post("/login")
async def login(
    payload: UserLogin,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[RedisService, Depends(get_redis)],
):
    """Authenticate user. Returns tokens or 2FA challenge."""
    auth_service = AuthService(db, redis)
    settings_service = SettingsService(db)
    user = await auth_service.authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    app_settings = await settings_service.get_all_settings()
    two_factor_required = (
        bool(app_settings.get("two_factor_auth", False))
        and user.two_factor_enabled
    )

    if two_factor_required:
        import time
        temp_token = _generate_temp_token()
        _clean_expired_temp_tokens()
        _pending_2fa[temp_token] = {
            "user_id": str(user.id),
            "expires_at": time.time() + 300,  # 5 minutes
        }
        return {
            "two_factor_required": True,
            "temp_token": temp_token,
        }

    tokens = auth_service.generate_tokens(
        user,
        access_token_minutes=int(app_settings["session_timeout"]),
    )

    # Audit
    audit = AuditService(db)
    await audit.log(
        action=AuditAction.LOGIN,
        resource_type="user",
        resource_id=str(user.id),
        user_id=user.id,
        description=f"User logged in: {user.email}",
        trace_id=request.state.trace_id if hasattr(request.state, "trace_id") else None,
        ip_address=request.client.host if request.client else None,
    )
    return tokens


@router.post("/verify-otp", response_model=TokenPair)
async def verify_otp(
    payload: VerifyOtpRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[RedisService, Depends(get_redis)],
):
    """Verify 2FA OTP code using temporary token."""
    _clean_expired_temp_tokens()

    pending = _pending_2fa.pop(payload.temp_token, None)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired temporary token",
        )

    user_service = UserService(db)
    user = await user_service.get_by_id(pending["user_id"])
    if not user or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA not configured",
        )

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(payload.otp_code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OTP code",
        )

    auth_service = AuthService(db, redis)
    settings_service = SettingsService(db)
    app_settings = await settings_service.get_all_settings()
    tokens = auth_service.generate_tokens(
        user,
        access_token_minutes=int(app_settings["session_timeout"]),
    )

    audit = AuditService(db)
    await audit.log(
        action=AuditAction.LOGIN,
        resource_type="user",
        resource_id=str(user.id),
        user_id=user.id,
        description=f"User completed 2FA login: {user.email}",
        trace_id=request.state.trace_id if hasattr(request.state, "trace_id") else None,
        ip_address=request.client.host if request.client else None,
    )
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    payload: TokenRefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[RedisService, Depends(get_redis)],
):
    """Refresh an expired access token."""
    auth_service = AuthService(db, redis)
    settings_service = SettingsService(db)
    app_settings = await settings_service.get_all_settings()
    tokens = await auth_service.refresh_tokens(
        payload.refresh_token,
        access_token_minutes=int(app_settings["session_timeout"]),
    )
    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return tokens


@router.post("/logout", response_model=MessageOut)
async def logout(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[RedisService, Depends(get_redis)],
):
    """Blacklist current tokens."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    auth_service = AuthService(db, redis)
    await auth_service.logout(access_token=token)

    # Audit
    audit = AuditService(db)
    await audit.log(
        action=AuditAction.LOGOUT,
        resource_type="user",
        resource_id=str(current_user.id),
        user_id=current_user.id,
        description=f"User logged out: {current_user.email}",
        trace_id=request.state.trace_id if hasattr(request.state, "trace_id") else None,
        ip_address=request.client.host if request.client else None,
    )
    return {"message": "Successfully logged out"}


@router.post("/2fa/setup", response_model=SetupTwoFactorResponse)
async def setup_two_factor(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate TOTP secret and QR code for authenticator apps."""
    import io
    import base64
    import qrcode

    if current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled",
        )

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.email,
        issuer_name="L2T Support",
    )

    # Generate QR code as base64 PNG data URL
    qr = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    qr_data_url = f"data:image/png;base64,{qr_b64}"

    # Store secret temporarily; user must verify with OTP to activate
    current_user.totp_secret = secret
    from app.schemas.user import UserUpdate as AuthUserUpdate

    user_service = UserService(db)
    await user_service.update_user(current_user.id, AuthUserUpdate(totp_secret=secret))

    return SetupTwoFactorResponse(
        secret=secret,
        qr_code_url=qr_data_url,
    )


@router.post("/2fa/verify-setup", response_model=MessageOut)
async def verify_two_factor_setup(
    payload: VerifyTwoFactorSetupRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verify OTP and activate 2FA for the current user."""
    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA not initialized. Call setup first.",
        )

    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(payload.otp_code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OTP code",
        )

    from app.schemas.user import UserUpdate as AuthUserUpdate

    user_service = UserService(db)
    await user_service.update_user(current_user.id, AuthUserUpdate(two_factor_enabled=True))
    return {"message": "Two-factor authentication enabled"}


@router.post("/2fa/disable", response_model=MessageOut)
async def disable_two_factor(
    payload: DisableTwoFactorRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disable 2FA after confirming the user's password."""
    from app.core.security import verify_password

    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    from app.schemas.user import UserUpdate as AuthUserUpdate

    user_service = UserService(db)
    await user_service.update_user(current_user.id, AuthUserUpdate(
        two_factor_enabled=False,
        totp_secret=None,
    ))
    return {"message": "Two-factor authentication disabled"}
