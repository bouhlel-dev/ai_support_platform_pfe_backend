"""
Admin settings schemas.
"""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


ThemeMode = Literal["light", "dark", "system"]
AutoAssignmentMethod = Literal["Round-robin", "By category", "By workload"]
MailMode = Literal["gmail", "smtp"]
SmtpEncryption = Literal["tls", "ssl", "none"]


class AdminSettingsResponse(BaseModel):
    app_name: str
    support_email: EmailStr
    description: str
    locale: str
    timezone: str
    primary_color: str
    secondary_color: str
    theme_mode: ThemeMode
    ticket_label: str
    auto_assignment: bool
    auto_assignment_method: AutoAssignmentMethod
    allow_client_close: bool
    sla_critical_hours: int
    sla_high_hours: int
    sla_medium_hours: int
    sla_low_hours: int
    min_password_length: int
    session_timeout: int
    max_login_attempts: int
    password_complexity: bool
    allow_registration: bool
    require_email_verification: bool
    two_factor_auth: bool
    require_admin_profile_completion: bool
    mail_mode: MailMode
    gmail_from_email: str
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    smtp_from_name: str
    smtp_from_email: str
    smtp_host: str
    smtp_port: int
    smtp_encryption: SmtpEncryption
    smtp_username: str
    smtp_password: str
    notify_new_ticket: bool
    notify_status_change: bool
    notify_assigned: bool
    notify_overdue: bool
    notify_resolved: bool
    ai_auto_reply_chat_enabled: bool
    ai_auto_reply_whatsapp_enabled: bool
    ai_auto_reply_email_enabled: bool
    conversation_sla_autopilot_enabled: bool
    conversation_sla_auto_escalate_minutes_before_breach: int
    conversation_sla_auto_assign_enabled: bool
    conversation_sla_auto_assign_minutes_before_breach: int
    conversation_sla_autopilot_respect_snooze: bool
    sms_api_url: str = ""
    sms_api_key: str = ""
    sms_sender: str = "L2T"
    sms_language: str = "en"
    sms_notify_new_ticket: bool = False
    sms_notify_status_change: bool = False
    sms_notify_reply: bool = False
    sms_notify_resolved: bool = False


class GeneralSettingsUpdate(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=100)
    support_email: EmailStr
    description: str = ""
    locale: str = Field("en", min_length=2, max_length=16)
    timezone: str = Field("UTC", min_length=2, max_length=64)


class BrandingSettingsUpdate(BaseModel):
    primary_color: str = Field(..., min_length=4, max_length=32)
    secondary_color: str = Field(..., min_length=4, max_length=32)
    theme_mode: ThemeMode = "light"
    ticket_label: str = Field(..., min_length=1, max_length=64)


class TicketSettingsUpdate(BaseModel):
    auto_assignment: bool
    auto_assignment_method: AutoAssignmentMethod = "Round-robin"
    allow_client_close: bool
    sla_critical_hours: int = Field(..., ge=1, le=999)
    sla_high_hours: int = Field(..., ge=1, le=999)
    sla_medium_hours: int = Field(..., ge=1, le=999)
    sla_low_hours: int = Field(..., ge=1, le=999)


class SecuritySettingsUpdate(BaseModel):
    min_password_length: int = Field(..., ge=6, le=64)
    session_timeout: int = Field(..., ge=5, le=1440)
    max_login_attempts: int = Field(..., ge=3, le=50)
    password_complexity: bool
    allow_registration: bool
    require_email_verification: bool
    two_factor_auth: bool
    require_admin_profile_completion: bool = False


class NotificationSettingsUpdate(BaseModel):
    mail_mode: MailMode = "gmail"
    gmail_from_email: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    smtp_from_name: str = "Support"
    smtp_from_email: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_encryption: SmtpEncryption = "tls"
    smtp_username: str = ""
    smtp_password: str = ""
    notify_new_ticket: bool
    notify_status_change: bool
    notify_assigned: bool
    notify_overdue: bool
    notify_resolved: bool
    sms_api_url: str = ""
    sms_api_key: str = ""
    sms_sender: str = "L2T"
    sms_language: str = "en"
    sms_notify_new_ticket: bool = False
    sms_notify_status_change: bool = False
    sms_notify_reply: bool = False
    sms_notify_resolved: bool = False


class SmsTestRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)
    message: str = Field("", max_length=160)
    language: str = "en"


class AutomationSettingsUpdate(BaseModel):
    ai_auto_reply_chat_enabled: bool
    ai_auto_reply_whatsapp_enabled: bool
    ai_auto_reply_email_enabled: bool
    conversation_sla_autopilot_enabled: bool
    conversation_sla_auto_escalate_minutes_before_breach: int = Field(..., ge=0, le=24 * 60)
    conversation_sla_auto_assign_enabled: bool
    conversation_sla_auto_assign_minutes_before_breach: int = Field(..., ge=0, le=24 * 60)
    conversation_sla_autopilot_respect_snooze: bool


class PublicAuthSettingsResponse(BaseModel):
    app_name: str
    description: str
    allow_registration: bool
    min_password_length: int
    password_complexity: bool
