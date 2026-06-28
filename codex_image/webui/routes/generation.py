from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile

from codex_image.client import DEFAULT_MAIN_MODEL, image_model_supports_input_fidelity
from codex_image.webui.context import WebUIContext
from codex_image.webui.executor import (
    _file_to_data_url,
    _instructions_for_transport,
    _normalize_compression,
    _normalize_prompt_fidelity,
    _prompt_for_transport,
    _resolve_gallery_refs,
    _resolve_reference_assets,
)
from codex_image.webui.prompt_ratio import append_ratio_prompt_instruction
from codex_image.webui.storage import utc_now
from codex_image.webui.task_metadata import _dedupe_preserve_order, _params, _reference_asset_response, _with_file_urls, _write_queued_metadata
from codex_image.webui.yuanshu_resources import yuanshu_gallery_storage
from codex_image.webui.yuanshu_scope import current_yuanshu_owner_for_request, current_yuanshu_session, stamp_current_yuanshu_owner
from codex_image.webui.yuanshu import verify_yuanshu_token

DEFAULT_PROMPT_FIDELITY = "strict"
ACTIVE_DEDUPLICATION_STATUSES = {"submitting", "queued", "running"}
YUANSHU_ALLOWED_RESOLUTIONS = {"auto", "standard", "2k", "4k"}
YUANSHU_MIN_SIZE_DIMENSION = 16
YUANSHU_MAX_SIZE_DIMENSION = 3840
YUANSHU_SIZE_MULTIPLE = 16
YUANSHU_MIN_SIZE_PIXELS = 655360
YUANSHU_MAX_SIZE_PIXELS = 8294400
YUANSHU_MAX_LONG_SHORT_RATIO = 3
YUANSHU_SIZE_PATTERN = re.compile(r"^(\d+)x(\d+)$")
YUANSHU_ALLOWED_SIZES = {
    "auto",
    "1024x1024",
    "1024x1280",
    "1280x1024",
    "1152x1536",
    "1536x1152",
    "1024x1536",
    "1536x1024",
    "864x1536",
    "1536x864",
    "672x1568",
    "1568x672",
    "2048x2048",
    "1600x2000",
    "2000x1600",
    "1536x2048",
    "2048x1536",
    "1344x2016",
    "2016x1344",
    "1152x2048",
    "2048x1152",
    "1152x2688",
    "2688x1152",
    "2880x2880",
    "2560x3200",
    "3200x2560",
    "2448x3264",
    "3264x2448",
    "2336x3504",
    "3504x2336",
    "2160x3840",
    "3840x2160",
    "1632x3808",
    "3808x1632",
}


def _is_yuanshu_size_enabled(size: str) -> bool:
    if size in YUANSHU_ALLOWED_SIZES:
        return True

    match = YUANSHU_SIZE_PATTERN.fullmatch(size)
    if match is None:
        return False

    width = int(match.group(1))
    height = int(match.group(2))
    if width < YUANSHU_MIN_SIZE_DIMENSION or height < YUANSHU_MIN_SIZE_DIMENSION:
        return False
    if width > YUANSHU_MAX_SIZE_DIMENSION or height > YUANSHU_MAX_SIZE_DIMENSION:
        return False
    if width % YUANSHU_SIZE_MULTIPLE != 0 or height % YUANSHU_SIZE_MULTIPLE != 0:
        return False

    short_side = min(width, height)
    long_side = max(width, height)
    if long_side / short_side > YUANSHU_MAX_LONG_SHORT_RATIO:
        return False

    pixels = width * height
    return YUANSHU_MIN_SIZE_PIXELS <= pixels <= YUANSHU_MAX_SIZE_PIXELS


def _is_yuanshu_request(api_provider_id: str | None, api_mode: str | None) -> bool:
    return str(api_provider_id or "").strip().lower() == "yuanshu" or str(api_mode or "").strip().lower() == "yuanshu"


async def _verify_yuanshu_session_token(yuanshu_session: dict[str, Any], ctx: WebUIContext) -> None:
    try:
        await asyncio.to_thread(
            verify_yuanshu_token,
            str(yuanshu_session.get("token") or ""),
            server_api_base=str(yuanshu_session.get("server_api_base") or ctx.yuanshu.server_api_base),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _enforce_yuanshu_generation_limits(size: str, resolution: str | None, n: int) -> tuple[str, str | None, int]:
    clean_size = str(size or "auto").strip().lower() or "auto"
    clean_resolution = str(resolution or "").strip().lower()
    try:
        clean_n = int(n)
    except (TypeError, ValueError):
        clean_n = 1
    if clean_n < 1 or clean_n > 2:
        raise HTTPException(status_code=400, detail="Yuanshu mode supports at most 2 images per task")
    if clean_resolution and clean_resolution not in YUANSHU_ALLOWED_RESOLUTIONS:
        raise HTTPException(status_code=400, detail="This image resolution is not enabled in Yuanshu mode")
    if not _is_yuanshu_size_enabled(clean_size):
        raise HTTPException(status_code=400, detail="This image size is not enabled in Yuanshu mode")
    return clean_size, (clean_resolution or resolution), clean_n


def _owner_matches_current_user(candidate: dict[str, Any], owner: dict[str, Any]) -> bool:
    return str(candidate.get("user_id") or "") == str(owner.get("user_id") or "")


def _reference_asset_matches_current_owner(item: dict[str, Any], owner: dict[str, Any]) -> bool:
    candidates: list[dict[str, Any]] = []
    legacy_owner = item.get("yuanshu_owner")
    if isinstance(legacy_owner, dict):
        candidates.append(legacy_owner)
    owners = item.get("yuanshu_owners")
    if isinstance(owners, list):
        candidates.extend(candidate for candidate in owners if isinstance(candidate, dict))
    return any(_owner_matches_current_user(candidate, owner) for candidate in candidates)


async def _upload_file_fingerprints(files: list[UploadFile]) -> list[dict[str, str]]:
    fingerprints: list[dict[str, str]] = []
    for upload in files:
        data = await upload.read()
        await upload.seek(0)
        if not data:
            continue
        fingerprints.append(
            {
                "sha256": hashlib.sha256(data).hexdigest(),
                "filename": str(upload.filename or "image.png"),
                "content_type": str(upload.content_type or ""),
            }
        )
    return fingerprints


def _request_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _generate_request_fingerprint_payload(
    *,
    prompt: str,
    prompt_for_model: str,
    main_model: str,
    model: str,
    size: str,
    resolution: str | None,
    ratio: str | None,
    orientation: str | None,
    quality: str,
    output_format: str,
    moderation: str | None,
    output_compression: str | None,
    n: int,
    prompt_fidelity: str,
    web_search: bool,
    api_provider_id: str | None,
    api_mode: str | None,
    codex_mode: str | None,
    gallery_image_ids: list[str],
    reference_asset_ids: list[str],
    upload_fingerprints: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "mode": "generate",
        "prompt": str(prompt or ""),
        "prompt_for_model": str(prompt_for_model or ""),
        "main_model": str(main_model or ""),
        "model": str(model or ""),
        "size": str(size or ""),
        "resolution": str(resolution or ""),
        "ratio": str(ratio or ""),
        "orientation": str(orientation or ""),
        "quality": str(quality or ""),
        "output_format": str(output_format or ""),
        "moderation": str(moderation or ""),
        "output_compression": str(output_compression or ""),
        "n": int(n),
        "prompt_fidelity": str(prompt_fidelity or ""),
        "web_search": bool(web_search),
        "api_provider_id": str(api_provider_id or ""),
        "api_mode": str(api_mode or ""),
        "codex_mode": str(codex_mode or ""),
        "gallery_image_ids": list(gallery_image_ids),
        "reference_asset_ids": list(reference_asset_ids),
        "upload_fingerprints": list(upload_fingerprints),
    }


def _find_active_duplicate_task(ctx: WebUIContext, owner: dict[str, Any] | None, request_fingerprint: str) -> dict[str, Any] | None:
    owner_user_id = str(owner.get("user_id") or "") if owner is not None else ""
    if not owner_user_id or not request_fingerprint:
        return None
    for candidate in ctx.storage.list_recent_tasks(limit=500, yuanshu_user_id=owner_user_id):
        task_id = str(candidate.get("task_id") or "")
        if not task_id:
            continue
        try:
            metadata = ctx.storage.read_metadata(task_id)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if str(metadata.get("request_fingerprint") or "") != request_fingerprint:
            continue
        if str(metadata.get("status") or "") in ACTIVE_DEDUPLICATION_STATUSES:
            metadata["task_id"] = str(metadata.get("task_id") or task_id)
            return metadata
    return None


def _resolve_owned_reference_assets(ctx: WebUIContext, request: Request, asset_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    owner = current_yuanshu_owner_for_request(ctx, request)
    if owner is None:
        return _resolve_reference_assets(ctx.reference_asset_storage, asset_ids)
    refs: list[dict[str, Any]] = []
    data_urls: list[str] = []
    for asset_id in _dedupe_preserve_order(asset_ids):
        try:
            item = ctx.reference_asset_storage.read_item(asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid reference asset id: {asset_id}") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Reference asset not found: {asset_id}") from exc
        if not _reference_asset_matches_current_owner(item, owner):
            raise HTTPException(status_code=404, detail=f"Reference asset not found: {asset_id}")
        item = ctx.reference_asset_storage.touch(asset_id)
        path = ctx.reference_asset_storage.image_path(asset_id)
        refs.append(_reference_asset_response(item))
        data_urls.append(_file_to_data_url(path, mime_type=str(item.get("mime_type") or "")))
    return refs, data_urls


def register_generation_routes(app: FastAPI, ctx: WebUIContext) -> None:
    h = ctx.route_helpers

    @app.post("/api/generate")
    async def generate(
        request: Request,
        prompt: str = Form(...),
        main_model: str = Form(DEFAULT_MAIN_MODEL),
        model: str = Form("gpt-image-2"),
        size: str = Form("auto"),
        resolution: str | None = Form(None),
        ratio: str | None = Form(None),
        orientation: str | None = Form(None),
        quality: str = Form("low"),
        background: str | None = Form(None),
        output_format: str = Form("png"),
        moderation: str | None = Form(None),
        output_compression: str | None = Form(None),
        n: int = Form(1, ge=1, le=4),
        web_search: bool = Form(False),
        codex_mode: str | None = Form(None),
        api_mode: str | None = Form(None),
        api_provider_id: str | None = Form(None),
        prompt_for_model: str | None = Form(None),
        prompt_fidelity: str = Form(DEFAULT_PROMPT_FIDELITY),
        gallery_image_ids: list[str] | None = Form(None),
        reference_asset_ids: list[str] | None = Form(None),
        reference_images: list[UploadFile] | None = File(None),
    ) -> dict[str, Any]:
        yuanshu_session = current_yuanshu_session(ctx, request)
        if yuanshu_session is None and _is_yuanshu_request(api_provider_id, api_mode):
            raise HTTPException(status_code=401, detail="Yuanshu image playground session is not ready")
        if yuanshu_session is None and not ctx.auth_checker():
            raise HTTPException(status_code=401, detail="Codex auth is not available")
        if yuanshu_session is not None:
            await _verify_yuanshu_session_token(yuanshu_session, ctx)
            size, resolution, n = _enforce_yuanshu_generation_limits(size, resolution, n)

        owner = current_yuanshu_owner_for_request(ctx, request)
        gallery_storage = yuanshu_gallery_storage(ctx, request)
        clean_gallery_image_ids = _dedupe_preserve_order(gallery_image_ids or [])
        clean_reference_asset_ids = _dedupe_preserve_order(reference_asset_ids or [])
        upload_fingerprints = await _upload_file_fingerprints(reference_images or [])
        request_fingerprint = _request_fingerprint(
            _generate_request_fingerprint_payload(
                prompt=prompt,
                prompt_for_model=prompt_for_model or prompt,
                main_model=main_model,
                model=model,
                size=size,
                resolution=resolution,
                ratio=ratio,
                orientation=orientation,
                quality=quality,
                output_format=output_format,
                moderation=moderation,
                output_compression=output_compression,
                n=n,
                prompt_fidelity=prompt_fidelity,
                web_search=web_search,
                api_provider_id="yuanshu" if yuanshu_session is not None else api_provider_id,
                api_mode="images" if yuanshu_session is not None else api_mode,
                codex_mode=codex_mode,
                gallery_image_ids=clean_gallery_image_ids,
                reference_asset_ids=clean_reference_asset_ids,
                upload_fingerprints=upload_fingerprints,
            )
        )
        duplicate_task = _find_active_duplicate_task(ctx, owner, request_fingerprint)
        if duplicate_task is not None:
            try:
                duplicate_request = ctx.storage.read_request(str(duplicate_task["task_id"]))
            except (FileNotFoundError, OSError, ValueError):
                duplicate_request = {}
            return {
                "task": _with_file_urls(duplicate_task, ctx.active_task_ids, gallery_storage, ctx.reference_asset_storage),
                "request": duplicate_request,
                "duplicate": True,
            }

        gallery_refs, gallery_data_urls = _resolve_gallery_refs(gallery_storage, clean_gallery_image_ids)
        uploaded_assets = await h["save_reference_assets"](reference_images or [], request=request)
        selected_assets, _ = _resolve_owned_reference_assets(ctx, request, clean_reference_asset_ids)
        reference_assets = h["dedupe_reference_assets"](uploaded_assets + selected_assets)
        task = ctx.storage.create_task("generate")
        created_at = utc_now()
        input_files: list[Path] = []
        reference_data_urls = [
            _file_to_data_url(ctx.reference_asset_storage.image_path(str(item["id"])), mime_type=str(item.get("mime_type") or ""))
            for item in reference_assets
        ]
        all_reference_data_urls = reference_data_urls + gallery_data_urls
        compression = _normalize_compression(output_format, output_compression)
        fidelity = _normalize_prompt_fidelity(prompt_fidelity)
        model_prompt = append_ratio_prompt_instruction(h["model_prompt_for_fidelity"](prompt, prompt_for_model, fidelity), ratio)
        prompt_constraints, guard_instructions = h["prompt_guard_context"](prompt, fidelity)
        auth_source = ctx.auth_settings.read_source() if not h["client_factory_overridden"] else "codex"
        effective_api_provider_id = h["request_api_provider_id"](auth_source, api_provider_id)
        effective_api_provider_name = h["request_api_provider_name"](auth_source, effective_api_provider_id)
        effective_api_mode = h["request_api_mode"](auth_source, api_mode, effective_api_provider_id)
        effective_codex_mode = h["request_codex_mode"](auth_source, codex_mode)
        effective_api_images_concurrency = h["request_api_images_concurrency"](auth_source, effective_api_provider_id)
        requested_backend = h["backend_for_submit"](auth_source, effective_api_mode, effective_codex_mode)
        if yuanshu_session is not None:
            auth_source = "api"
            effective_api_provider_id = "yuanshu"
            effective_api_provider_name = "元枢"
            effective_api_mode = "images"
            effective_codex_mode = None
            effective_api_images_concurrency = 1
            requested_backend = "openai_images"
        transport_mode = effective_api_mode or effective_codex_mode
        web_search_enabled = bool(web_search) and requested_backend.endswith("_responses")
        request_model_prompt = _prompt_for_transport(
            model_prompt,
            auth_source=auth_source,
            api_mode=transport_mode,
            prompt_fidelity=fidelity,
            instructions=guard_instructions,
        )
        request_instructions = _instructions_for_transport(
            auth_source=auth_source,
            api_mode=transport_mode,
            instructions=guard_instructions,
        )

        request_kwargs: dict[str, Any] = dict(
            auth_source=auth_source,
            api_mode=effective_api_mode,
            codex_mode=effective_codex_mode,
            prompt=request_model_prompt,
            main_model=main_model,
            model=model,
            input_images=all_reference_data_urls,
            size=size,
            quality=quality,
            background=background,
            output_format=output_format,
            moderation=moderation,
            output_compression=compression,
        )
        if request_instructions:
            request_kwargs["instructions"] = request_instructions
        if web_search_enabled:
            request_kwargs["web_search"] = True
        request_payload = h["build_image_request_payload"](**request_kwargs)
        stored_request_payload = h["slim_request_payload"](
            request_payload,
            input_files=[path.name for path in input_files],
            gallery_refs=gallery_refs,
            reference_assets=reference_assets,
        )
        stored_request_payload["webui_request_fingerprint"] = request_fingerprint
        stored_request_payload["webui_requested_backend"] = requested_backend
        if effective_api_provider_id is not None:
            stored_request_payload["webui_api_provider_id"] = effective_api_provider_id
        if effective_api_provider_name:
            stored_request_payload["webui_api_provider_name"] = effective_api_provider_name
        if auth_source == "api" and effective_api_mode == "images":
            stored_request_payload["webui_api_images_concurrency"] = effective_api_images_concurrency
        ctx.storage.write_request(task.task_id, stored_request_payload)
        params = _params(main_model, model, size, quality, background, output_format, moderation, compression, n)
        if resolution:
            params["resolution"] = resolution
        if ratio:
            params["ratio"] = ratio
        if orientation:
            params["orientation"] = orientation
        params["prompt_fidelity"] = fidelity
        if web_search_enabled:
            params["web_search"] = True
        if effective_codex_mode is not None:
            params["codex_mode"] = effective_codex_mode
        if effective_api_mode is not None:
            params["api_mode"] = effective_api_mode
        if effective_api_provider_id is not None:
            params["api_provider_id"] = effective_api_provider_id
        if effective_api_provider_name:
            params["api_provider_name"] = effective_api_provider_name
        if auth_source == "api" and effective_api_mode == "images":
            params["api_images_concurrency"] = effective_api_images_concurrency
        metadata = _write_queued_metadata(
            ctx.storage,
            task.task_id,
            created_at=created_at,
            mode="generate",
            prompt=prompt,
            prompt_for_model=model_prompt,
            params=params,
            input_files=[path.name for path in input_files],
            mask_file=None,
            gallery_refs=gallery_refs,
            reference_assets=reference_assets,
            prompt_constraints=prompt_constraints,
            requested_backend=requested_backend,
            max_attempts=ctx.queue_manager.max_attempts if ctx.queue_manager is not None else 1,
        )
        metadata["request_fingerprint"] = request_fingerprint
        metadata = stamp_current_yuanshu_owner(ctx, metadata, request)
        ctx.storage.write_metadata(task.task_id, metadata)
        ctx.queue_storage.enqueue(task.task_id)
        h["ensure_queue_worker_running"]()
        return {
            "task": _with_file_urls(metadata, ctx.active_task_ids, gallery_storage, ctx.reference_asset_storage),
            "request": stored_request_payload,
        }

    @app.post("/api/edit")
    async def edit(
        request: Request,
        prompt: str = Form(...),
        main_model: str = Form(DEFAULT_MAIN_MODEL),
        model: str = Form("gpt-image-2"),
        size: str = Form("auto"),
        resolution: str | None = Form(None),
        ratio: str | None = Form(None),
        orientation: str | None = Form(None),
        quality: str = Form("low"),
        background: str | None = Form(None),
        output_format: str = Form("png"),
        input_fidelity: str | None = Form(None),
        moderation: str | None = Form(None),
        output_compression: str | None = Form(None),
        n: int = Form(1, ge=1, le=4),
        web_search: bool = Form(False),
        codex_mode: str | None = Form(None),
        api_mode: str | None = Form(None),
        api_provider_id: str | None = Form(None),
        prompt_for_model: str | None = Form(None),
        prompt_fidelity: str = Form(DEFAULT_PROMPT_FIDELITY),
        gallery_image_ids: list[str] | None = Form(None),
        reference_asset_ids: list[str] | None = Form(None),
        images: list[UploadFile] | None = File(None),
        mask: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        yuanshu_session = current_yuanshu_session(ctx, request)
        if yuanshu_session is None and _is_yuanshu_request(api_provider_id, api_mode):
            raise HTTPException(status_code=401, detail="Yuanshu image playground session is not ready")
        if yuanshu_session is None and not ctx.auth_checker():
            raise HTTPException(status_code=401, detail="Codex auth is not available")
        if yuanshu_session is not None:
            await _verify_yuanshu_session_token(yuanshu_session, ctx)
            raise HTTPException(status_code=403, detail="Image edit is not enabled in Yuanshu mode")

        if not images and not _dedupe_preserve_order(gallery_image_ids or []) and not _dedupe_preserve_order(reference_asset_ids or []):
            raise HTTPException(status_code=400, detail="At least one image is required")
        gallery_storage = yuanshu_gallery_storage(ctx, request)
        gallery_refs, gallery_data_urls = _resolve_gallery_refs(gallery_storage, gallery_image_ids or [])
        uploaded_assets = await h["save_reference_assets"](images or [])
        selected_assets, _ = _resolve_reference_assets(ctx.reference_asset_storage, reference_asset_ids or [])
        reference_assets = h["dedupe_reference_assets"](uploaded_assets + selected_assets)
        task = ctx.storage.create_task("edit")
        created_at = utc_now()
        input_files: list[Path] = []
        if not reference_assets and not gallery_data_urls:
            raise HTTPException(status_code=400, detail="At least one image is required")
        mask_files = await h["save_uploads"](task.task_id, [mask] if mask is not None else [], kind="mask")
        image_data_urls = [
            _file_to_data_url(ctx.reference_asset_storage.image_path(str(item["id"])), mime_type=str(item.get("mime_type") or ""))
            for item in reference_assets
        ]
        all_image_data_urls = image_data_urls + gallery_data_urls
        mask_data_url = _file_to_data_url(mask_files[0]) if mask_files else None
        compression = _normalize_compression(output_format, output_compression)
        fidelity = _normalize_prompt_fidelity(prompt_fidelity)
        model_prompt = append_ratio_prompt_instruction(h["model_prompt_for_fidelity"](prompt, prompt_for_model, fidelity), ratio)
        prompt_constraints, guard_instructions = h["prompt_guard_context"](prompt, fidelity)
        effective_input_fidelity = input_fidelity if image_model_supports_input_fidelity(model) else None
        auth_source = ctx.auth_settings.read_source() if not h["client_factory_overridden"] else "codex"
        effective_api_provider_id = h["request_api_provider_id"](auth_source, api_provider_id)
        effective_api_provider_name = h["request_api_provider_name"](auth_source, effective_api_provider_id)
        effective_api_mode = h["request_api_mode"](auth_source, api_mode, effective_api_provider_id)
        effective_codex_mode = h["request_codex_mode"](auth_source, codex_mode)
        effective_api_images_concurrency = h["request_api_images_concurrency"](auth_source, effective_api_provider_id)
        requested_backend = h["backend_for_submit"](auth_source, effective_api_mode, effective_codex_mode)
        transport_mode = effective_api_mode or effective_codex_mode
        web_search_enabled = bool(web_search) and requested_backend.endswith("_responses")
        request_model_prompt = _prompt_for_transport(
            model_prompt,
            auth_source=auth_source,
            api_mode=transport_mode,
            prompt_fidelity=fidelity,
            instructions=guard_instructions,
        )
        request_instructions = _instructions_for_transport(
            auth_source=auth_source,
            api_mode=transport_mode,
            instructions=guard_instructions,
        )

        request_kwargs = dict(
            auth_source=auth_source,
            api_mode=effective_api_mode,
            codex_mode=effective_codex_mode,
            prompt=request_model_prompt,
            action="edit",
            main_model=main_model,
            model=model,
            input_images=all_image_data_urls,
            mask_image=mask_data_url,
            size=size,
            quality=quality,
            background=background,
            output_format=output_format,
            input_fidelity=effective_input_fidelity,
            moderation=moderation,
            output_compression=compression,
        )
        if request_instructions:
            request_kwargs["instructions"] = request_instructions
        if web_search_enabled:
            request_kwargs["web_search"] = True
        request_payload = h["build_image_request_payload"](**request_kwargs)
        image_input_names = [path.name for path in input_files]
        mask_file = mask_files[0].name if mask_files else None
        stored_request_payload = h["slim_request_payload"](
            request_payload,
            input_files=image_input_names,
            gallery_refs=gallery_refs,
            reference_assets=reference_assets,
            mask_file=mask_file,
        )
        stored_request_payload["webui_requested_backend"] = requested_backend
        if effective_api_provider_id is not None:
            stored_request_payload["webui_api_provider_id"] = effective_api_provider_id
        if effective_api_provider_name:
            stored_request_payload["webui_api_provider_name"] = effective_api_provider_name
        if auth_source == "api" and effective_api_mode == "images":
            stored_request_payload["webui_api_images_concurrency"] = effective_api_images_concurrency
        ctx.storage.write_request(task.task_id, stored_request_payload)
        params = _params(main_model, model, size, quality, background, output_format, moderation, compression, n)
        if resolution:
            params["resolution"] = resolution
        if ratio:
            params["ratio"] = ratio
        if orientation:
            params["orientation"] = orientation
        params["prompt_fidelity"] = fidelity
        if effective_input_fidelity:
            params["input_fidelity"] = effective_input_fidelity
        if web_search_enabled:
            params["web_search"] = True
        if effective_codex_mode is not None:
            params["codex_mode"] = effective_codex_mode
        if effective_api_mode is not None:
            params["api_mode"] = effective_api_mode
        if effective_api_provider_id is not None:
            params["api_provider_id"] = effective_api_provider_id
        if effective_api_provider_name:
            params["api_provider_name"] = effective_api_provider_name
        if auth_source == "api" and effective_api_mode == "images":
            params["api_images_concurrency"] = effective_api_images_concurrency
        metadata = _write_queued_metadata(
            ctx.storage,
            task.task_id,
            created_at=created_at,
            mode="edit",
            prompt=prompt,
            prompt_for_model=model_prompt,
            params=params,
            input_files=image_input_names,
            mask_file=mask_file,
            gallery_refs=gallery_refs,
            reference_assets=reference_assets,
            prompt_constraints=prompt_constraints,
            requested_backend=requested_backend,
            max_attempts=ctx.queue_manager.max_attempts if ctx.queue_manager is not None else 1,
        )
        ctx.queue_storage.enqueue(task.task_id)
        h["ensure_queue_worker_running"]()
        return {
                "task": _with_file_urls(metadata, ctx.active_task_ids, gallery_storage, ctx.reference_asset_storage),
                "request": stored_request_payload,
            }
