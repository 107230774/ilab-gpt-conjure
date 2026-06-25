from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from codex_image.client import DEFAULT_IMAGE_MODEL, OpenAIImagesImageClient


YUANSHU_API_BASE = "/image-playground/api/v1"
YUANSHU_SERVER_API_BASE = "https://yuans.vip/image-playground/api/v1"


@dataclass
class YuanshuBootstrapState:
    token: str = ""
    api_base: str = YUANSHU_API_BASE
    server_api_base: str = YUANSHU_SERVER_API_BASE
    model: str = DEFAULT_IMAGE_MODEL
    key_id: int | None = None
    key_name: str = ""
    group_id: int | None = None
    group_name: str = ""
    token_expires_at: str = ""

    def update(self, payload: dict[str, Any]) -> None:
        self.token = str(payload.get("token") or "").strip()
        self.api_base = _same_origin_api_base(payload.get("apiBase") or payload.get("api_base") or YUANSHU_API_BASE)
        self.server_api_base = _server_api_base()
        self.model = str(payload.get("model") or DEFAULT_IMAGE_MODEL).strip() or DEFAULT_IMAGE_MODEL
        self.key_id = _int_or_none(payload.get("keyId") or payload.get("key_id"))
        self.key_name = str(payload.get("keyName") or payload.get("key_name") or "").strip()
        self.group_id = _int_or_none(payload.get("groupId") or payload.get("group_id"))
        self.group_name = str(payload.get("groupName") or payload.get("group_name") or "").strip()
        self.token_expires_at = str(payload.get("tokenExpiresAt") or payload.get("token_expires_at") or "").strip()

    def public(self) -> dict[str, Any]:
        return {
            "ready": bool(self.token),
            "api_base": self.api_base,
            "model": self.model,
            "key_id": self.key_id,
            "key_name": self.key_name,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "token_expires_at": self.token_expires_at,
        }


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _same_origin_api_base(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw.startswith("/") or "://" in raw or raw.startswith("//"):
        return YUANSHU_API_BASE
    return raw.rstrip("/") or YUANSHU_API_BASE


def _server_api_base() -> str:
    raw = os.getenv("YUANSHU_IMAGE_PLAYGROUND_API_BASE", "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    return YUANSHU_SERVER_API_BASE


def yuanshu_session_verify_url(server_api_base: str | None = None) -> str:
    raw = (server_api_base or _server_api_base()).rstrip("/")
    return raw + "/session/verify"


def verify_yuanshu_token(token: str, *, server_api_base: str | None = None) -> dict[str, Any]:
    clean_token = str(token or "").strip()
    if not clean_token:
        raise RuntimeError("Yuanshu image playground token is required")
    url = yuanshu_session_verify_url(server_api_base)
    with httpx.Client(timeout=5.0) as client:
        response = client.post(url, json={"token": clean_token})
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code == 401:
        raise PermissionError(str(data.get("detail") or "Yuanshu image playground session expired"))
    if response.status_code == 403:
        raise PermissionError(str(data.get("detail") or "Yuanshu image playground key is unavailable"))
    if response.status_code >= 400 or not data.get("ok"):
        raise RuntimeError(str(data.get("detail") or "Yuanshu image playground session verification failed"))
    return data


def yuanshu_client(state: YuanshuBootstrapState) -> OpenAIImagesImageClient:
    if not state.token:
        raise RuntimeError("Yuanshu image playground session is not ready")
    return OpenAIImagesImageClient(
        api_key=state.token,
        base_url=state.server_api_base,
        image_model=state.model,
    )


def yuanshu_client_from_session(session: dict[str, Any]) -> OpenAIImagesImageClient:
    token = str(session.get("token") or "").strip()
    if not token:
        raise RuntimeError("Yuanshu image playground session is not ready")
    base_url = str(session.get("server_api_base") or YUANSHU_SERVER_API_BASE).strip() or YUANSHU_SERVER_API_BASE
    model = str(session.get("model") or DEFAULT_IMAGE_MODEL).strip() or DEFAULT_IMAGE_MODEL
    return OpenAIImagesImageClient(
        api_key=token,
        base_url=base_url.rstrip("/"),
        image_model=model,
    )
