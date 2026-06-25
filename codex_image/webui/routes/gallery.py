from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from codex_image.webui.context import WebUIContext
from codex_image.webui.storage import _guess_mime_type
from codex_image.webui.task_metadata import _gallery_category_response, _gallery_item_response, _reference_asset_response
from codex_image.webui.yuanshu_scope import current_yuanshu_owner_for_request, metadata_matches_current_yuanshu_owner


def register_gallery_routes(app: FastAPI, ctx: WebUIContext) -> None:
    @app.get("/api/gallery")
    def list_gallery(category: str | None = None) -> dict[str, Any]:
        try:
            items = ctx.gallery_storage.list_items(category=category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": [_gallery_item_response(item) for item in items],
            "categories": [_gallery_category_response(category) for category in ctx.gallery_storage.list_categories()],
        }

    @app.get("/api/gallery/categories")
    def list_gallery_categories() -> dict[str, Any]:
        return {"categories": [_gallery_category_response(category) for category in ctx.gallery_storage.list_categories()]}

    @app.post("/api/gallery/categories")
    def create_gallery_category(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            category = ctx.gallery_storage.create_category(
                name=str(payload["name"]),
                prompt_role=str(payload["prompt_role"]) if "prompt_role" in payload else None,
                order=int(payload["order"]) if "order" in payload and payload["order"] is not None else None,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"category": _gallery_category_response(category)}

    @app.patch("/api/gallery/categories/reorder")
    def reorder_gallery_categories(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            categories = ctx.gallery_storage.reorder_categories(list(payload["category_ids"]))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"categories": [_gallery_category_response(category) for category in categories]}

    @app.patch("/api/gallery/categories/{category_id}")
    def update_gallery_category(category_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            category = ctx.gallery_storage.update_category(
                category_id,
                name=str(payload["name"]) if "name" in payload else None,
                prompt_role=str(payload["prompt_role"]) if "prompt_role" in payload else None,
                order=int(payload["order"]) if "order" in payload and payload["order"] is not None else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Gallery category not found") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"category": _gallery_category_response(category)}

    @app.delete("/api/gallery/categories/{category_id}")
    def delete_gallery_category(category_id: str, move_to: str | None = None) -> dict[str, Any]:
        try:
            ctx.gallery_storage.delete_category(category_id, move_to=move_to)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Gallery category not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "id": category_id}

    @app.post("/api/gallery")
    async def create_gallery_item(
        name: str = Form(...),
        category: str = Form(...),
        prompt_note: str | None = Form(None),
        image: UploadFile = File(...),
    ) -> dict[str, Any]:
        data = await image.read()
        if not data:
            raise HTTPException(status_code=400, detail="Image is required")
        if image.content_type and not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {image.content_type}")
        try:
            item = ctx.gallery_storage.create_item(
                name=name,
                category=category,
                filename=image.filename or "image.png",
                data=data,
                content_type=image.content_type,
                prompt_note=prompt_note,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="Gallery name already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"item": _gallery_item_response(item)}

    @app.patch("/api/gallery/reorder")
    def reorder_gallery_items(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            items = ctx.gallery_storage.reorder_items(str(payload["category"]), list(payload["item_ids"]))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"items": [_gallery_item_response(item) for item in items]}

    @app.patch("/api/gallery/{item_id}")
    def update_gallery_item(item_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            item = ctx.gallery_storage.update_item(
                item_id,
                name=str(payload["name"]) if "name" in payload else None,
                category=str(payload["category"]) if "category" in payload else None,
                prompt_note=str(payload["prompt_note"]) if "prompt_note" in payload else None,
                order=int(payload["order"]) if "order" in payload and payload["order"] is not None else None,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="Gallery name already exists") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Gallery item not found") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"item": _gallery_item_response(item)}

    @app.put("/api/gallery/{item_id}/image")
    async def replace_gallery_item_image(item_id: str, image: UploadFile = File(...)) -> dict[str, Any]:
        data = await image.read()
        if not data:
            raise HTTPException(status_code=400, detail="Image is required")
        if image.content_type and not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {image.content_type}")
        try:
            item = ctx.gallery_storage.replace_item_image(
                item_id,
                filename=image.filename or "image.png",
                data=data,
                content_type=image.content_type,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Gallery item not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"item": _gallery_item_response(item)}

    @app.delete("/api/gallery/{item_id}")
    def delete_gallery_item(item_id: str) -> dict[str, Any]:
        try:
            ctx.gallery_storage.delete_item(item_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Gallery item not found") from exc
        return {"ok": True, "id": item_id}

    @app.get("/api/gallery/{item_id}/image")
    def get_gallery_image(item_id: str) -> Response:
        try:
            item = ctx.gallery_storage.read_item(item_id)
            path = ctx.gallery_storage.image_path(item_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Gallery item not found") from exc
        return FileResponse(
            path,
            media_type=str(item.get("mime_type") or "application/octet-stream"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/reference-assets/recent")
    def list_reference_assets(request: Request, limit: int = 20) -> dict[str, Any]:
        clean_limit = max(0, min(int(limit), 50))
        allowed_ids = _current_owner_reference_asset_ids(ctx, request)
        return {
            "items": [
                _reference_asset_response(item)
                for item in ctx.reference_asset_storage.list_recent(limit=max(clean_limit * 10, 200))
                if _reference_asset_matches_current_owner(item, ctx, request) or str(item.get("id") or "") in allowed_ids
            ][:clean_limit]
        }

    @app.delete("/api/reference-assets/{asset_id}")
    def delete_reference_asset(asset_id: str, request: Request) -> dict[str, bool]:
        if not _reference_asset_id_matches_current_owner(asset_id, ctx, request):
            raise HTTPException(status_code=404, detail=f"Reference asset not found: {asset_id}")
        try:
            ctx.reference_asset_storage.delete_item(asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid reference asset id") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Reference asset not found: {asset_id}") from exc
        return {"ok": True}

    @app.get("/api/reference-assets/{asset_id}/image")
    def get_reference_asset_image(asset_id: str, request: Request) -> Response:
        if not _reference_asset_id_matches_current_owner(asset_id, ctx, request):
            raise HTTPException(status_code=404, detail=f"Reference asset not found: {asset_id}")
        try:
            item = ctx.reference_asset_storage.read_item(asset_id)
            path = ctx.reference_asset_storage.image_path(asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid reference asset id") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Reference asset not found: {asset_id}") from exc
        return FileResponse(path, media_type=str(item.get("mime_type") or _guess_mime_type(path.name)))


def _reference_asset_id_matches_current_owner(asset_id: str, ctx: WebUIContext, request: Request) -> bool:
    try:
        item = ctx.reference_asset_storage.read_item(asset_id)
    except (FileNotFoundError, OSError, ValueError):
        item = {}
    if _reference_asset_matches_current_owner(item, ctx, request):
        return True
    return asset_id in _current_owner_reference_asset_ids(ctx, request)


def _reference_asset_matches_current_owner(item: Any, ctx: WebUIContext, request: Request) -> bool:
    owner = current_yuanshu_owner_for_request(ctx, request)
    if owner is None or not isinstance(item, dict):
        return False
    owners = item.get("yuanshu_owners")
    candidates = owners if isinstance(owners, list) else []
    legacy_owner = item.get("yuanshu_owner")
    if isinstance(legacy_owner, dict):
        candidates = [legacy_owner, *candidates]
    return any(_owner_matches(candidate, owner) for candidate in candidates if isinstance(candidate, dict))


def _owner_matches(candidate: dict[str, Any], owner: dict[str, Any]) -> bool:
    owner_user_id = str(owner.get("user_id") or "")
    if not owner_user_id:
        return False
    return str(candidate.get("user_id") or "") == owner_user_id


def _current_owner_reference_asset_ids(ctx: WebUIContext, request: Request) -> set[str]:
    asset_ids: set[str] = set()
    for task in _current_owner_full_tasks(ctx, request):
        assets = task.get("reference_assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if isinstance(asset, dict) and asset.get("id"):
                asset_ids.add(str(asset["id"]))
    return asset_ids


def _current_owner_full_tasks(ctx: WebUIContext, request: Request) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for candidate in ctx.storage.list_tasks():
        task_id = str(candidate.get("task_id") or "")
        if not task_id:
            continue
        try:
            metadata = ctx.storage.read_metadata(task_id)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        metadata["task_id"] = str(metadata.get("task_id") or task_id)
        if metadata_matches_current_yuanshu_owner(ctx, metadata, request):
            tasks.append(metadata)
    return tasks
