"""
SMS service for sending test and production SMS messages.
"""

import logging
from typing import Any

import httpx

from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class SmsService:
    def __init__(self, settings_service: SettingsService):
        self.settings_service = settings_service

    async def _get_config(self) -> dict[str, str]:
        api_url = await self.settings_service.get_str("sms_api_url")
        api_key = await self.settings_service.get_str("sms_api_key")
        sender = await self.settings_service.get_str("sms_sender")
        return {
            "api_url": api_url.strip(),
            "api_key": api_key.strip(),
            "sender": sender.strip() or "L2T",
        }

    def is_configured(self, config: dict[str, str]) -> bool:
        return bool(config["api_url"]) and bool(config["api_key"])

    @staticmethod
    def normalize_phone(phone: str) -> str:
        phone = "".join(c for c in phone if c.isdigit())
        if phone.startswith("00216"):
            phone = phone[5:]
        if phone.startswith("216") and len(phone) == 11:
            return phone
        if len(phone) == 8:
            return "216" + phone
        if phone.startswith("0") and len(phone) == 9:
            return "216" + phone[1:]
        return phone

    async def send(self, to: str, message: str) -> bool:
        config = await self._get_config()
        if not self.is_configured(config):
            logger.warning("SmsService: not configured — SMS not sent to %s", to)
            return False

        phone = self.normalize_phone(to)
        message = message.strip()[:160]

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.post(
                    config["api_url"],
                    headers={"Authorization": f"Bearer {config['api_key']}"},
                    data={
                        "type": "55",
                        "sender": config["sender"],
                        "sms[0][mobile]": phone,
                        "sms[0][sms]": message,
                    },
                )

            response_body = response.text.strip()
            status_code = None
            try:
                json_body = response.json()
                if isinstance(json_body, list) and len(json_body) > 0:
                    status_code = json_body[0].get("status")
                elif isinstance(json_body, dict):
                    status_code = json_body.get("status")
            except Exception:
                pass

            success = response.status_code < 400 or status_code == 200

            if success:
                logger.info("SmsService: SMS sent to %s | HTTP %s | response: %s", phone, response.status_code, response_body)
                return True
            else:
                logger.warning(
                    "SmsService: failed to %s | HTTP %s | response: %s",
                    phone, response.status_code, response_body,
                )
                return False

        except Exception as e:
            logger.error("SmsService: exception — %s", str(e))
            return False

    async def test_connection(self, test_phone: str, message: str = "") -> dict[str, Any]:
        phone = self.normalize_phone(test_phone)
        msg = message.strip() if message.strip() else "Test valide"
        ok = await self.send(phone, msg)
        return {
            "success": ok,
            "message": (
                f"SMS test envoye a {phone}"
                if ok
                else "Echec envoi — verifiez l'URL et la cle API"
            ),
        }
