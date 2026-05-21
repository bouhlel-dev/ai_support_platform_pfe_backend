"""
Authentication schemas (tokens).
"""

from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    sub: str
    exp: int
    type: str


class VerifyOtpRequest(BaseModel):
    temp_token: str
    otp_code: str


class SetupTwoFactorResponse(BaseModel):
    secret: str
    qr_code_url: str


class VerifyTwoFactorSetupRequest(BaseModel):
    otp_code: str


class DisableTwoFactorRequest(BaseModel):
    password: str
