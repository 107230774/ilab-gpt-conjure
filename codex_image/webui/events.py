from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from .context import WebUIContext
from .task_metadata import _gallery_item_response, _with_file_urls
from .yuanshu_scope import current_yuanshu_owner_for_request, filter_current_yuanshu_tasks, metadata_matches_current_yuanshu_owner


def queue_snapshot(ctx: WebUIContext, request: Request | None = None) -> dict[str, Any]:
    state = ctx.queue_storage.read_state()
    active_ids = ctx.route_helpers["visible_running_task_ids"]()
    waiting = [
        _with_file_urls(task, active_ids, ctx.gallery_storage, ctx.reference_asset_storage, include_request=False)
        for task in filter_current_yuanshu_tasks(
            ctx,
            [ctx.storage.read_metadata(task_id) for task_id in state["waiting"] if ctx.storage.metadata_path(task_id).exists()],
            request,
        )
    ]
    running = []
    for channel_id, item in state["running"].items():
        metadata_path = ctx.storage.metadata_path(str(item.get("task_id") or "")) if isinstance(item, dict) else None
        if metadata_path is None or not metadata_path.exists():
            continue
        metadata = ctx.storage.read_metadata(str(item["task_id"]))
        if not metadata_matches_current_yuanshu_owner(ctx, metadata, request):
            continue
        task = _with_file_urls(
            metadata,
            active_ids,
            ctx.gallery_storage,
            ctx.reference_asset_storage,
            include_request=False,
        )
        task["channel_id"] = channel_id
        task["account_id"] = item.get("account_id")
        running.append(task)
    channels = ctx.queue_manager.channels if ctx.queue_manager is not None else []
    queue_channel_available = ctx.route_helpers["queue_channel_available"]
    return {
        "waiting": waiting,
        "running": running,
        "summary": {
            "waiting_count": len(waiting),
            "running_count": len(running),
            "channel_count": len(channels),
            "usable_channel_count": sum(1 for channel in channels if queue_channel_available(channel)),
        },
    }


def event_snapshot(ctx: WebUIContext, request: Request | None = None) -> dict[str, Any]:
    owner = current_yuanshu_owner_for_request(ctx, request)
    user_id = str(owner.get("user_id") or "").strip() if owner is not None else ""
    recent_cards = ctx.storage.list_recent_task_cards(limit=200, yuanshu_user_id=user_id) if user_id else []
    return {
        "type": "snapshot",
        "tasks": filter_current_yuanshu_tasks(ctx, recent_cards, request),
        "queue": queue_snapshot(ctx, request),
        "gallery": [_gallery_item_response(item) for item in ctx.gallery_storage.list_items()],
        "auth": ctx.route_helpers["auth_event_payload"](),
    }


def sse_message(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def event_key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def queued_or_running_task_ids(queue: dict[str, Any]) -> set[str]:
    return {
        str(task.get("task_id"))
        for task in list(queue.get("waiting") or []) + list(queue.get("running") or [])
        if isinstance(task, dict) and task.get("task_id")
    }


def task_event(ctx: WebUIContext, task_id: str, request: Request | None = None) -> dict[str, Any] | None:
    if not ctx.storage.metadata_path(task_id).exists():
        return None
    metadata = ctx.storage.read_metadata(task_id)
    if not metadata_matches_current_yuanshu_owner(ctx, metadata, request):
        return None
    return {
        "type": "task",
        "task": _with_file_urls(
            metadata,
            ctx.route_helpers["visible_running_task_ids"](),
            ctx.gallery_storage,
            ctx.reference_asset_storage,
            include_request=False,
        ),
    }
