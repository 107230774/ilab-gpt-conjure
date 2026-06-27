from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import Request

from .context import WebUIContext
from .storage import GalleryStorage
from .settings_store import PromptSnippetSettings, PromptTemplateSettings
from .yuanshu_scope import YUANSHU_OWNER_KEY, current_yuanshu_owner_for_request


def current_yuanshu_user_id(ctx: WebUIContext, request: Request | None) -> str:
    owner = current_yuanshu_owner_for_request(ctx, request)
    return str(owner.get("user_id") or "").strip() if owner is not None else ""


def yuanshu_gallery_storage(ctx: WebUIContext, request: Request | None) -> GalleryStorage:
    user_id = current_yuanshu_user_id(ctx, request)
    return yuanshu_gallery_storage_for_user(ctx, user_id)


def yuanshu_gallery_storage_for_task(ctx: WebUIContext, metadata: dict[str, Any] | None) -> GalleryStorage:
    owner = metadata.get(YUANSHU_OWNER_KEY) if isinstance(metadata, dict) else None
    return yuanshu_gallery_storage_for_owner(ctx, owner if isinstance(owner, dict) else None)


def yuanshu_gallery_storage_for_owner(ctx: WebUIContext, owner: dict[str, Any] | None) -> GalleryStorage:
    user_id = str(owner.get("user_id") or "").strip() if owner is not None else ""
    return yuanshu_gallery_storage_for_user(ctx, user_id)


def yuanshu_gallery_storage_for_user(ctx: WebUIContext, user_id: str) -> GalleryStorage:
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        return ctx.gallery_storage
    return GalleryStorage(_yuanshu_user_resource_root(ctx, clean_user_id) / "gallery")


def yuanshu_prompt_snippet_settings(ctx: WebUIContext, request: Request | None) -> PromptSnippetSettings:
    user_id = current_yuanshu_user_id(ctx, request)
    if not user_id:
        return ctx.prompt_snippet_settings
    return PromptSnippetSettings(_yuanshu_user_resource_root(ctx, user_id) / "prompt-snippets.json")


def yuanshu_prompt_template_settings(ctx: WebUIContext, request: Request | None) -> PromptTemplateSettings:
    user_id = current_yuanshu_user_id(ctx, request)
    if not user_id:
        return ctx.prompt_template_settings
    return PromptTemplateSettings(_yuanshu_user_resource_root(ctx, user_id) / "prompt-templates.json")


def _yuanshu_user_resource_root(ctx: WebUIContext, user_id: str) -> Path:
    return ctx.source_data_root / "yuanshu-users" / _safe_yuanshu_user_id(user_id)


def _safe_yuanshu_user_id(value: Any) -> str:
    text = str(value or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip(".-")
    return safe[:80] or "anonymous"
