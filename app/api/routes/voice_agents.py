"""
Admin-only routes to configure and control the voice agents process.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import jwt
from pydantic import BaseModel

from app.api.deps import get_current_user, require_admin, require_any_authenticated
from app.core.config import get_settings
from app.db.models.user import User
from app.schemas.voice_agent import (
    VoiceAgentActionResponse,
    VoiceAgentConfig,
    VoiceAgentConfigResponse,
    VoiceAgentLogsResponse,
    VoiceAgentStartRequest,
    VoiceAgentStatusResponse,
)
from app.schemas.support_call_screen_context import (
    SupportCallScreenContextIngestRequest,
    SupportCallScreenContextIngestResponse,
)
from app.schemas.voice_agent import VoiceEscalationRequest, VoiceEscalationResponse
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services.ticket_service import TicketService
from app.db.models.enums import ChannelType, TicketPriority, TicketStatus
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.support_call_screen_context import support_call_screen_context_store

settings = get_settings()
router = APIRouter(prefix="/voice-agents", tags=["Voice Agents Admin"])


import httpx


class VoiceAgentProcessManagerProxy:
    def __init__(self) -> None:
        self.control_url = os.getenv("VOICE_AGENTS_CONTROL_URL", "http://voice_agents:9001")
        self.project_root = Path(__file__).resolve().parents[3]
        self.runtime_dir = self.project_root / "uploads"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.runtime_dir / "voice_agents_control.json"

    def get_effective_config(self) -> VoiceAgentConfig:
        base = VoiceAgentConfig(
            livekit_api_key=settings.LIVEKIT_API_KEY,
            livekit_api_secret=settings.LIVEKIT_API_SECRET,
            livekit_url=settings.LIVEKIT_URL,
            ai_response_provider=settings.AI_RESPONSE_PROVIDER,
            use_realtime=settings.USE_REALTIME,
            google_api_key=settings.GOOGLE_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            # Store the full comma-separated string so rotation is preserved
            gemini_api_key=settings.current_gemini_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            backend_api_url=os.getenv("BACKEND_API_URL", "http://localhost:8000"),
            internal_service_key=settings.INTERNAL_SERVICE_KEY,
            voice_recordings_dir=os.getenv("VOICE_RECORDINGS_DIR", "recordings"),
            database_url=settings.DATABASE_URL,
        )

        if not self.config_file.exists():
            return base

        try:
            saved_raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            saved_cfg = VoiceAgentConfig(**saved_raw)
            return saved_cfg
        except Exception:
            return base

    def save_config(self, config: VoiceAgentConfig) -> None:
        self.config_file.write_text(
            json.dumps(config.model_dump(), indent=2),
            encoding="utf-8",
        )

    def start(self, mode: Literal["dev", "start"]) -> None:
        cfg = self.get_effective_config()

        # Use the rotation properties — both VoiceAgentConfig (Pydantic) and
        # VoiceAgentSettings (dataclass) now expose current_gemini_key /
        # current_google_key, so this call is safe on either type.
        env_vars = {
            "LIVEKIT_API_KEY": cfg.livekit_api_key,
            "LIVEKIT_API_SECRET": cfg.livekit_api_secret,
            "LIVEKIT_URL": cfg.livekit_url,
            "AI_RESPONSE_PROVIDER": cfg.ai_response_provider,
            "USE_REALTIME": "true" if cfg.use_realtime else "false",
            "GOOGLE_API_KEY": cfg.current_google_key or "",   # ← rotated
            "OPENAI_API_KEY": cfg.openai_api_key or "",
            "ANTHROPIC_API_KEY": cfg.anthropic_api_key or "",
            "GEMINI_API_KEY": cfg.current_gemini_key or "",   # ← rotated
            "GEMINI_MODEL": cfg.gemini_model or "",
            "OPENAI_MODEL": cfg.openai_model or "",
            "BACKEND_API_URL": cfg.backend_api_url,
            "INTERNAL_SERVICE_KEY": cfg.internal_service_key,
            "VOICE_RECORDINGS_DIR": cfg.voice_recordings_dir,
            "DATABASE_URL": cfg.database_url,
        }

        try:
            resp = httpx.post(
                f"{self.control_url}/start",
                json={"mode": mode, "env_vars": env_vars},
                timeout=10.0,
            )
            if resp.status_code == 409:
                raise RuntimeError("Voice agents process is already running")
            resp.raise_for_status()
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Voice agents container unreachable ({self.control_url}). Is Docker running?"
            ) from exc

    def stop(self) -> bool:
        try:
            resp = httpx.post(f"{self.control_url}/stop", timeout=10.0)
            resp.raise_for_status()
            return resp.json().get("message") == "stopped"
        except Exception:
            return False

    def status(self) -> VoiceAgentStatusResponse:
        try:
            resp = httpx.get(f"{self.control_url}/status", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            started_at = data.get("started_at")
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            return VoiceAgentStatusResponse(
                running=data.get("running", False),
                pid=data.get("pid"),
                mode=data.get("mode"),
                started_at=started_at,
                uptime_seconds=data.get("uptime_seconds"),
                log_file=data.get("log_file"),
                last_exit_code=data.get("last_exit_code"),
            )
        except Exception:
            return VoiceAgentStatusResponse(
                running=False,
                pid=None,
                mode=None,
                started_at=None,
                uptime_seconds=None,
                log_file=None,
                last_exit_code=None,
            )

    def read_logs(self, lines: int = 200) -> list[str]:
        try:
            resp = httpx.get(
                f"{self.control_url}/logs", params={"lines": lines}, timeout=5.0
            )
            resp.raise_for_status()
            return resp.json().get("lines", [])
        except Exception:
            return ["Unable to fetch logs. Is the voice agents container running?"]


manager = VoiceAgentProcessManagerProxy()
manager_lock = asyncio.Lock()


@router.get(
    "/config",
    response_model=VoiceAgentConfigResponse,
    dependencies=[Depends(require_admin)],
)
async def get_voice_agent_config(_: User = Depends(get_current_user)):
    return VoiceAgentConfigResponse(config=manager.get_effective_config())


@router.put(
    "/config",
    response_model=VoiceAgentConfigResponse,
    dependencies=[Depends(require_admin)],
)
async def update_voice_agent_config(
    payload: VoiceAgentConfig,
    _: User = Depends(get_current_user),
):
    manager.save_config(payload)
    return VoiceAgentConfigResponse(config=payload)


@router.get(
    "/status",
    response_model=VoiceAgentStatusResponse,
    dependencies=[Depends(require_admin)],
)
async def get_voice_agent_status(_: User = Depends(get_current_user)):
    status_obj = manager.status()
    if importlib.util.find_spec("livekit") is None and not status_obj.running:
        status_obj = status_obj.model_copy(
            update={
                "last_exit_code": (
                    status_obj.last_exit_code
                    if status_obj.last_exit_code is not None
                    else 127
                )
            }
        )
    return status_obj


@router.post(
    "/start",
    response_model=VoiceAgentActionResponse,
    dependencies=[Depends(require_admin)],
)
async def start_voice_agents(
    payload: VoiceAgentStartRequest,
    _: User = Depends(get_current_user),
):
    async with manager_lock:
        try:
            manager.start(payload.mode)
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start voice agents: {exc}",
            )

    return VoiceAgentActionResponse(message=f"Voice agents started in '{payload.mode}' mode")


@router.post(
    "/stop",
    response_model=VoiceAgentActionResponse,
    dependencies=[Depends(require_admin)],
)
async def stop_voice_agents(_: User = Depends(get_current_user)):
    async with manager_lock:
        stopped = manager.stop()

    if not stopped:
        return VoiceAgentActionResponse(message="Voice agents are not running")
    return VoiceAgentActionResponse(message="Voice agents stopped")


@router.get(
    "/logs",
    response_model=VoiceAgentLogsResponse,
    dependencies=[Depends(require_admin)],
)
async def get_voice_agent_logs(
    _: User = Depends(get_current_user),
    lines: int = Query(200, ge=1, le=1000),
):
    return VoiceAgentLogsResponse(lines=manager.read_logs(lines=lines))


class TokenResponse(BaseModel):
    token: str
    url: str


def _build_livekit_token_response(
    *,
    identity: str,
    room_name: str,
    cfg: VoiceAgentConfig,
) -> TokenResponse:
    if not cfg.livekit_api_key or not cfg.livekit_api_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LiveKit API Key or Secret not configured",
        )

    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": cfg.livekit_api_key,
        "sub": identity,
        "nbf": now,
        "exp": now + 3600,
        "video": {
            "room": room_name,
            "roomJoin": True,
        },
    }

    token = jwt.encode(payload, cfg.livekit_api_secret, algorithm="HS256")

    frontend_url = cfg.livekit_url or "ws://localhost:7880"
    if "livekit:7880" in frontend_url:
        frontend_url = frontend_url.replace("livekit:7880", "127.0.0.1:7880")

    return TokenResponse(token=token, url=frontend_url)


@router.get(
    "/test-token",
    response_model=TokenResponse,
    dependencies=[Depends(require_admin)],
)
async def get_test_token(_: User = Depends(get_current_user)):
    """Generate a valid LiveKit token using python-jose for frontend testing."""
    cfg = manager.get_effective_config()
    return _build_livekit_token_response(
        identity="admin-tester",
        room_name="support-room",
        cfg=cfg,
    )


@router.get(
    "/support-call-token",
    response_model=TokenResponse,
    dependencies=[Depends(require_any_authenticated)],
)
async def get_support_call_token(current_user: User = Depends(get_current_user)):
    cfg = manager.get_effective_config()
    return _build_livekit_token_response(
        identity=f"{current_user.role.value.lower()}-{current_user.id}",
        room_name=f"support-call-{current_user.id}",
        cfg=cfg,
    )


@router.post(
    "/support-call-screen-context",
    response_model=SupportCallScreenContextIngestResponse,
    dependencies=[Depends(require_any_authenticated)],
)
async def ingest_support_call_screen_context(
    payload: SupportCallScreenContextIngestRequest,
    current_user: User = Depends(get_current_user),
):
    room_name = f"support-call-{current_user.id}"
    try:
        result = support_call_screen_context_store.upsert(room_name, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SupportCallScreenContextIngestResponse(**result)


@router.post(
    "/escalate",
    response_model=VoiceEscalationResponse,
    dependencies=[Depends(require_admin)],
)
async def escalate_voice_call(
    payload: VoiceEscalationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin endpoint: create a high-priority escalation ticket for a voice call."""
    room_name = payload.room_name.strip()
    reason = payload.reason.strip()
    if not room_name or not reason:
        raise HTTPException(status_code=400, detail="room_name and reason are required")

    ticket_service = TicketService(db)
    ticket = await ticket_service.create_ticket(
        current_user.id,
        TicketCreate(
            subject=f"Voice Call Escalation: {room_name}",
            description="\n".join(
                [
                    f"**Escalation Reason:** {reason}",
                    f"**Room Name:** {room_name}",
                    *(
                        [f"**Audio Recording:** `{payload.audio_file_path}`"]
                        if payload.audio_file_path
                        else []
                    ),
                    *(
                        ["\n**--- Transcript ---**", payload.transcript]
                        if payload.transcript
                        else []
                    ),
                ]
            ),
            priority=TicketPriority.HIGH,
            channel_source=ChannelType.CALL_TRANSCRIPT,
        ),
    )

    escalated_ticket = await ticket_service.update_ticket(
        ticket.id,
        TicketUpdate(status=TicketStatus.ESCALATED, escalation_flag=True),
    )
    if not escalated_ticket:
        raise HTTPException(status_code=500, detail="Escalation ticket update failed")

    return VoiceEscalationResponse(
        room_name=room_name,
        ticket_id=str(escalated_ticket.id),
        ticket_subject=escalated_ticket.subject,
        status=escalated_ticket.status.value,
        escalation_flag=bool(escalated_ticket.escalation_flag),
    )
