from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from codex_image.webui.context import WebUIContext
from codex_image.webui.events import queue_snapshot
from codex_image.webui.storage import _sidebar_task_card, utc_now
from codex_image.webui.yuanshu_scope import current_yuanshu_owner_for_request, local_unowned_tasks_visible, metadata_matches_current_yuanshu_owner


def register_dashboard_routes(app: FastAPI, ctx: WebUIContext) -> None:
    def current_yuanshu_user_id(request: Request) -> str:
        owner = current_yuanshu_owner_for_request(ctx, request)
        return str(owner.get("user_id") or "").strip() if owner is not None else ""

    def owned_sidebar_card(task_id: str, request: Request) -> dict[str, Any] | None:
        try:
            metadata = ctx.storage.read_metadata(task_id)
        except (FileNotFoundError, OSError, ValueError):
            return None
        if not isinstance(metadata, dict):
            return None
        metadata["task_id"] = str(metadata.get("task_id") or task_id)
        if not metadata_matches_current_yuanshu_owner(ctx, metadata, request):
            return None
        return _sidebar_task_card(metadata)

    def recent_sidebar_cards(request: Request, limit: int) -> list[dict[str, Any]]:
        user_id = current_yuanshu_user_id(request)
        if not user_id and not local_unowned_tasks_visible(ctx, request):
            return []
        tasks: list[dict[str, Any]] = []
        tasks_by_id: dict[str, dict[str, Any]] = {}
        for card in ctx.storage.list_recent_task_cards(limit=limit, yuanshu_user_id=user_id):
            task_id = str(card.get("task_id") or "")
            owned_card = owned_sidebar_card(task_id, request)
            if owned_card is None:
                continue
            tasks_by_id[task_id] = owned_card
            tasks.append(owned_card)

        queue_state = ctx.queue_storage.read_state()
        active_ids = [
            *[str(task_id) for task_id in queue_state.get("waiting", []) if task_id],
            *[
                str(item.get("task_id"))
                for item in queue_state.get("running", {}).values()
                if isinstance(item, dict) and item.get("task_id")
            ],
        ]
        for task_id in active_ids:
            if task_id in tasks_by_id:
                continue
            task = owned_sidebar_card(task_id, request)
            if task is None:
                continue
            tasks_by_id[task_id] = task
            tasks.append(task)
        return tasks

    def snapshot_revision(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def etag_matches(request: Request, revision: str) -> bool:
        raw = request.headers.get("if-none-match", "")
        candidates = [item.strip().strip('"') for item in raw.split(",") if item.strip()]
        return revision in candidates

    @app.get("/api/dashboard/snapshot")
    async def dashboard_snapshot(request: Request, limit: int = Query(80, ge=1, le=200)) -> Response:
        ctx.route_helpers["ensure_queue_worker_running"]()
        queue = queue_snapshot(ctx, request)
        tasks = recent_sidebar_cards(request, limit)
        revision_payload = {
            "queue": queue,
            "tasks": tasks,
        }
        revision = snapshot_revision(revision_payload)
        etag = f'"{revision}"'
        headers = {
            "ETag": etag,
            "Cache-Control": "private, no-store",
        }
        if etag_matches(request, revision):
            return Response(status_code=304, headers=headers)
        return JSONResponse(
            {
                "revision": revision,
                "queue": queue,
                "tasks": tasks,
                "server_time": utc_now(),
            },
            headers=headers,
        )
