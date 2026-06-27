from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import HTTPException, Request

from .context import WebUIContext
from .yuanshu import verify_yuanshu_token

YUANSHU_OWNER_KEY = "yuanshu_owner"
YUANSHU_SESSION_REF_KEY = "yuanshu_session_ref"
YUANSHU_SESSION_COOKIE = "yuanshu_image_playground_session"


def new_yuanshu_session_id() -> str:
    return secrets.token_urlsafe(32)


def session_from_payload(ctx: WebUIContext, payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    verification = verify_yuanshu_token(token, server_api_base=ctx.yuanshu.server_api_base)
    key_id = _int_or_none(payload.get("keyId") or payload.get("key_id"))
    verified_user_id = _int_or_none(verification.get("user_id"))
    verified_key_id = _int_or_none(verification.get("key_id"))
    verified_group_id = _int_or_none(verification.get("group_id"))
    if key_id is not None and verified_key_id is not None and key_id != verified_key_id:
        raise PermissionError("Yuanshu image playground key mismatch")
    return {
        "token": token,
        "api_base": str(payload.get("apiBase") or payload.get("api_base") or "/image-playground/api/v1").strip(),
        "server_api_base": ctx.yuanshu.server_api_base,
        "model": str(payload.get("model") or ctx.yuanshu.model).strip() or ctx.yuanshu.model,
        "session_token_id": str(verification.get("session_id") or "").strip(),
        "user_id": verified_user_id or _int_or_none(payload.get("userId") or payload.get("user_id")),
        "key_id": verified_key_id or key_id,
        "key_name": str(payload.get("keyName") or payload.get("key_name") or "").strip(),
        "group_id": verified_group_id or _int_or_none(payload.get("groupId") or payload.get("group_id")),
        "group_name": str(payload.get("groupName") or payload.get("group_name") or "").strip(),
        "token_expires_at": str(payload.get("tokenExpiresAt") or payload.get("token_expires_at") or "").strip(),
    }


def current_yuanshu_session(ctx: WebUIContext, request: Request | None = None) -> dict[str, Any] | None:
    if request is not None:
        session_id = (
            request.headers.get("x-yuanshu-session", "")
            or request.cookies.get(YUANSHU_SESSION_COOKIE, "")
        ).strip()
        session = ctx.yuanshu_sessions.get(session_id)
        if isinstance(session, dict) and session.get("token") and session.get("key_id"):
            return session
        return None
    owner = current_yuanshu_owner(ctx)
    if owner is None:
        return None
    return {
        **owner,
        "token": ctx.yuanshu.token,
        "api_base": ctx.yuanshu.api_base,
        "server_api_base": ctx.yuanshu.server_api_base,
        "model": ctx.yuanshu.model,
        "token_expires_at": ctx.yuanshu.token_expires_at,
    }


def current_yuanshu_owner(ctx: WebUIContext) -> dict[str, Any] | None:
    key_id = ctx.yuanshu.key_id
    if not ctx.yuanshu.token or key_id is None:
        return None
    return {
        "key_id": key_id,
        "key_name": ctx.yuanshu.key_name,
        "group_id": ctx.yuanshu.group_id,
        "group_name": ctx.yuanshu.group_name,
    }


def current_yuanshu_owner_for_request(ctx: WebUIContext, request: Request | None = None) -> dict[str, Any] | None:
    session = current_yuanshu_session(ctx, request)
    if session is None:
        return None
    return {
        "user_id": session.get("user_id"),
        "key_id": session.get("key_id"),
        "key_name": session.get("key_name") or "",
        "group_id": session.get("group_id"),
        "group_name": session.get("group_name") or "",
        "session_token_id": session.get("session_token_id") or "",
    }


def stamp_current_yuanshu_owner(ctx: WebUIContext, metadata: dict[str, Any], request: Request | None = None) -> dict[str, Any]:
    owner = current_yuanshu_owner_for_request(ctx, request)
    if owner is not None:
        metadata[YUANSHU_OWNER_KEY] = owner
        if request is not None:
            session_id = request.headers.get("x-yuanshu-session", "").strip()
            if session_id:
                metadata[YUANSHU_SESSION_REF_KEY] = {
                    "session_id": session_id,
                    "session_token_id": owner.get("session_token_id") or "",
                }
    return metadata


def metadata_matches_current_yuanshu_owner(ctx: WebUIContext, metadata: dict[str, Any], request: Request | None = None) -> bool:
    owner = current_yuanshu_owner_for_request(ctx, request)
    if owner is None:
        task_owner = metadata.get(YUANSHU_OWNER_KEY)
        if isinstance(task_owner, dict):
            return False
        if not _yuanshu_public_mode_enabled():
            return True
        return local_unowned_tasks_visible(ctx, request)
    task_owner = metadata.get(YUANSHU_OWNER_KEY)
    if not isinstance(task_owner, dict):
        return False
    owner_user_id = str(owner.get("user_id") or "")
    if not owner_user_id:
        return False
    return str(task_owner.get("user_id") or "") == owner_user_id


def filter_current_yuanshu_tasks(ctx: WebUIContext, tasks: list[dict[str, Any]], request: Request | None = None) -> list[dict[str, Any]]:
    if current_yuanshu_owner_for_request(ctx, request) is None:
        if not _yuanshu_public_mode_enabled():
            return tasks
        return [task for task in tasks if metadata_matches_current_yuanshu_owner(ctx, task, request)]
    return [task for task in tasks if metadata_matches_current_yuanshu_owner(ctx, task, request)]


def require_current_yuanshu_task(ctx: WebUIContext, task_id: str, request: Request | None = None) -> dict[str, Any]:
    try:
        metadata = ctx.storage.read_metadata(task_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if not metadata_matches_current_yuanshu_owner(ctx, metadata, request):
        raise HTTPException(status_code=404, detail="Task not found") from None
    return metadata


def _yuanshu_public_mode_enabled() -> bool:
    raw = os.getenv("YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def local_unowned_tasks_visible(ctx: WebUIContext, request: Request | None) -> bool:
    if request is None:
        return False
    path = request.url.path
    if path == "/image-playground" or path.startswith("/image-playground/"):
        return False
    try:
        return bool(ctx.auth_checker())
    except Exception:
        return False


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
