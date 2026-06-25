from __future__ import annotations

import base64
from io import BytesIO
import json
import mimetypes
import os
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from codex_image.client import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_MAIN_MODEL,
    CodexImageClient,
    CodexImagesImageClient,
    ImageResult,
    OpenAIImagesImageClient,
    OpenAIResponsesImageClient,
    image_model_supports_input_fidelity,
)
from codex_image.prompt_guard import (
    build_guarded_prompt,
    build_original_prompt_instructions,
    build_prompt_guard_instructions,
    extract_prompt_constraints,
)

from .auth_routing import (
    API_MODES,
    AUTH_SOURCES,
    BACKEND_CODEX_IMAGES,
    BACKEND_CODEX_RESPONSES,
    BACKEND_OPENAI_IMAGES,
    BACKEND_OPENAI_RESPONSES,
    DEFAULT_API_IMAGES_CONCURRENCY,
    DEFAULT_API_MODE,
    MAX_API_IMAGES_CONCURRENCY,
    MIN_API_IMAGES_CONCURRENCY,
    _api_queue_channel_count,
    _apply_retry_api_provider,
    _auth_status,
    _backend_for_api_mode,
    _backend_for_submit,
    _client_for_auth_source,
    _codex_auth_available,
    _default_auth_source,
    _normalize_api_mode,
    _normalize_codex_mode,
    _queue_channels_for_source,
    _request_api_images_concurrency,
    _request_api_mode,
    _request_api_provider_id,
    _request_api_provider_name,
    _request_codex_mode,
    _task_metadata_uses_api,
    _update_stored_request_api_provider,
)
from .queue_runtime import (
    _client_for_queue_channel,
    _ensure_queue_worker_running,
    _queue_channel_available,
    _queue_channel_worker_loop,
    _queue_max_attempts_for_channels,
    _queue_worker_loop,
    execute_task,
    install_queue_runtime,
    queue_lifespan,
)
from .recovery import (
    _disk_output_paths,
    _is_legacy_auto_retry_queue_task,
    _materialize_orphaned_running_failure,
    _migrate_legacy_gallery_directory,
    _migrate_legacy_inputs,
    _migrate_legacy_mask,
    _migrate_legacy_outputs,
    _migrate_legacy_task_directories,
    _output_index_from_path,
    _prune_duplicate_request_payloads,
    _prune_missing_queue_tasks,
    _recover_completed_outputs_from_disk,
    _recover_queue_state,
    _recoverable_total_count,
)
from .schemas import (
    DEFAULT_WEBUI_AUTH_SETTINGS_PATH,
    DEFAULT_WEBUI_API_SETTINGS_PATH,
    DEFAULT_WEBUI_COLOR_SETTINGS_PATH,
    DEFAULT_WEBUI_GALLERY_SUBDIR,
    DEFAULT_WEBUI_OUTPUT_ROOT,
    DEFAULT_WEBUI_PROMPT_SNIPPETS_PATH,
    DEFAULT_WEBUI_PROMPT_TEMPLATES_PATH,
    DEFAULT_WEBUI_REFERENCE_ASSET_SUBDIR,
    DEFAULT_WEBUI_SETTINGS_PATH,
    DEFAULT_WEBUI_SOURCE_DATA_SUBDIR,
)
from .storage import GalleryStorage, QueueStorage, ReferenceAssetStorage, SQLiteQueueStorage, TaskStorage, _guess_mime_type, utc_now
from .settings_store import (
    ApiSettings,
    AuthSettings,
    ColorPaletteSettings,
    MAX_COLOR_IMPORT_BYTES,
    PromptSnippetSettings,
    PromptTemplateSettings,
    WebUISettings,
    _color_palette_css,
    _mask_api_key,
    _parse_color_palette_import,
)
from .context import WebUIContext
from .events import event_key, event_snapshot, queue_snapshot, queued_or_running_task_ids, sse_message, task_event
from .routes import register_webui_routes
from .executor import (
    _call_image_client,
    _debug_sse_path,
    _direct_images_concurrent_enabled,
    _file_to_data_url,
    _image_mime_type,
    _image_request_timeout_seconds,
    _instructions_for_transport,
    _normalize_compression,
    _normalize_prompt_fidelity,
    _noop_request_context,
    _parse_optional_int,
    _prompt_for_transport,
    _raise_if_task_cancelled,
    _restore_completed_output_progress,
    _resolve_gallery_refs,
    _resolve_reference_assets,
    _sniff_image_mime_type,
)
from .task_metadata import (
    _accept_partial_task_successes,
    _append_output_record_state,
    _api_images_concurrency_metadata_value,
    _apply_api_provider_metadata,
    _complete_task,
    _completed_output_records_for_accept,
    _dedupe_preserve_order,
    _downloadable_output_paths,
    _enrich_gallery_refs,
    _enrich_reference_assets,
    _fail_task,
    _finalize_generated_task,
    _gallery_category_response,
    _gallery_item_response,
    _gallery_ref_response,
    _infer_gallery_refs_from_prompt,
    _input_sources,
    _input_urls,
    _ordered_output_progress,
    _output_file_from_url,
    _output_url,
    _params,
    _partial_failure_message,
    _positive_int,
    _reference_asset_response,
    _retryable_failed_output_indexes,
    _with_file_urls,
    _write_progress_metadata,
    _write_queued_metadata,
    _write_running_metadata,
)
from .yuanshu_scope import current_yuanshu_owner_for_request, metadata_matches_current_yuanshu_owner

ClientFactory = Callable[[], Any]
AuthChecker = Callable[[], bool]
DEFAULT_IMAGE_REQUEST_TIMEOUT_SECONDS = 600.0
EVENT_STREAM_CHECK_INTERVAL_SECONDS = 1.0
PROMPT_FIDELITY_MODES = {"strict", "original", "off"}
DEFAULT_PROMPT_FIDELITY = "strict"


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


def _yuanshu_public_mode_enabled() -> bool:
    raw = os.getenv("YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _normalize_yuanshu_api_path(path: str) -> str:
    value = str(path or "")
    if value.startswith("/image-playground/api/"):
        return value.removeprefix("/image-playground")
    return value


def _yuanshu_public_api_blocked(method: str, path: str) -> bool:
    normalized = _normalize_yuanshu_api_path(path)
    verb = str(method or "").upper()
    if normalized in {"/api/settings", "/api/api-settings"}:
        return True
    if normalized == "/api/auth" and verb in {"PATCH", "POST", "PUT", "DELETE"}:
        return True
    if normalized == "/api/app-version/open-updater":
        return True
    if normalized == "/api/color-palette" and verb in {"PATCH", "POST", "PUT", "DELETE"}:
        return True
    if normalized.startswith("/api/color-palette/import") and verb == "POST":
        return True
    if normalized.startswith("/api/gallery") and verb in {"POST", "PATCH", "PUT", "DELETE"}:
        return True
    if normalized.startswith("/api/prompt-snippets") and verb in {"POST", "PATCH", "PUT", "DELETE"}:
        return True
    if normalized.startswith("/api/prompt-templates") and verb in {"POST", "PATCH", "PUT", "DELETE"}:
        return True
    if normalized.startswith("/api/prompt-template-categories") and verb in {"POST", "PATCH", "PUT", "DELETE"}:
        return True
    if normalized.startswith("/api/tasks/") and normalized.endswith("/reveal-output") and verb == "POST":
        return True
    return False


def create_app(
    *,
    input_root: Path | str | None = None,
    output_root: Path | str = DEFAULT_WEBUI_OUTPUT_ROOT,
    gallery_root: Path | str | None = None,
    reference_asset_root: Path | str | None = None,
    source_data_root: Path | str | None = None,
    client_factory: ClientFactory | None = None,
    auth_checker: AuthChecker | None = None,
    static_dir: Path | str | None = None,
    batch_delay_seconds: float = 5.0,
    auth_settings_path: Path | str = DEFAULT_WEBUI_AUTH_SETTINGS_PATH,
    api_settings_path: Path | str = DEFAULT_WEBUI_API_SETTINGS_PATH,
    color_settings_path: Path | str = DEFAULT_WEBUI_COLOR_SETTINGS_PATH,
    prompt_snippets_path: Path | str = DEFAULT_WEBUI_PROMPT_SNIPPETS_PATH,
    prompt_templates_path: Path | str = DEFAULT_WEBUI_PROMPT_TEMPLATES_PATH,
    webui_settings_path: Path | str = DEFAULT_WEBUI_SETTINGS_PATH,
    queue_path: Path | str | None = None,
    auto_start_queue: bool = True,
    auto_retry: bool = False,
) -> FastAPI:
    settings = WebUISettings(Path(webui_settings_path))
    configured_paths = settings.read_paths()
    custom_output = Path(output_root) != DEFAULT_WEBUI_OUTPUT_ROOT
    output_path = Path(output_root) if custom_output else configured_paths["output_root"]
    input_path = Path(input_root) if input_root is not None else (output_path / "inputs" if custom_output else configured_paths["input_root"])
    gallery_path = Path(gallery_root) if gallery_root is not None else (input_path / DEFAULT_WEBUI_GALLERY_SUBDIR if custom_output else configured_paths["gallery_root"])
    reference_asset_path = Path(reference_asset_root) if reference_asset_root is not None else input_path / DEFAULT_WEBUI_REFERENCE_ASSET_SUBDIR
    source_data_path = (
        Path(source_data_root)
        if source_data_root is not None
        else (output_path / DEFAULT_WEBUI_SOURCE_DATA_SUBDIR if custom_output else configured_paths["source_data_root"])
    )
    storage = TaskStorage(output_path, input_root=input_path, source_data_root=source_data_path)
    _migrate_legacy_gallery_directory(gallery_path, [Path("output") / "webui-gallery"])
    gallery_storage = GalleryStorage(gallery_path)
    reference_asset_storage = ReferenceAssetStorage(reference_asset_path)
    queue_storage = (
        QueueStorage(Path(queue_path))
        if queue_path is not None
        else SQLiteQueueStorage(source_data_path / "webui.db", legacy_json_path=source_data_path / "webui-queue.json")
    )
    _migrate_legacy_task_directories(storage, [Path("output") / "webui", Path(output_root)])
    _prune_duplicate_request_payloads(storage)
    _prune_missing_queue_tasks(queue_storage, storage)
    _recover_queue_state(storage, queue_storage)
    auth_settings = AuthSettings(Path(auth_settings_path))
    api_settings = ApiSettings(Path(api_settings_path))
    color_settings = ColorPaletteSettings(Path(color_settings_path))
    prompt_snippet_settings = PromptSnippetSettings(Path(prompt_snippets_path))
    prompt_template_settings = PromptTemplateSettings(Path(prompt_templates_path))
    static_path = Path(static_dir) if static_dir is not None else Path(__file__).parent / "static"
    make_client = client_factory or (lambda: _client_for_auth_source(auth_settings.read_source(), api_settings=api_settings))
    check_auth = auth_checker or (lambda: bool(_auth_status(auth_settings.read_source(), api_settings=api_settings)["auth_available"]))

    app = FastAPI(title="元枢在线生图", lifespan=queue_lifespan)

    @app.middleware("http")
    async def no_store_yuanshu_dynamic_responses(request: Request, call_next: Callable[[Request], Any]) -> Response:
        path = request.url.path
        if _yuanshu_public_mode_enabled() and _yuanshu_public_api_blocked(request.method, path):
            return JSONResponse(
                {"detail": "This management operation is disabled in Yuanshu public mode"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        if (
            path == "/"
            or path == "/history"
            or path == "/image-playground/"
            or path == "/image-playground/history"
            or path.startswith("/api/")
            or path.startswith("/image-playground/api/")
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    ctx = WebUIContext(
        app=app,
        storage=storage,
        gallery_storage=gallery_storage,
        reference_asset_storage=reference_asset_storage,
        queue_storage=queue_storage,
        webui_settings=settings,
        auth_settings=auth_settings,
        api_settings=api_settings,
        color_settings=color_settings,
        prompt_snippet_settings=prompt_snippet_settings,
        prompt_template_settings=prompt_template_settings,
        client_factory=make_client,
        auth_checker=check_auth,
        input_root=input_path,
        output_root=output_path,
        gallery_root=gallery_path,
        reference_asset_root=reference_asset_path,
        source_data_root=source_data_path,
        auto_start_queue=auto_start_queue,
    )
    ctx.install_on_app_state()

    queue_runtime = install_queue_runtime(
        ctx,
        batch_delay_seconds=batch_delay_seconds,
        auto_retry=auto_retry,
        client_factory_overridden=client_factory is not None,
    )
    if not _yuanshu_public_mode_enabled():
        app.mount("/inputs", StaticFiles(directory=input_path, check_dir=False), name="inputs")
    app.mount("/static", NoCacheStaticFiles(directory=static_path, check_dir=False), name="static")
    app.mount("/image-playground/static", NoCacheStaticFiles(directory=static_path, check_dir=False), name="yuanshu-static")

    @app.get("/", response_model=None)
    def index() -> Response:
        index_path = static_path / "index.html"
        if index_path.exists():
            return FileResponse(index_path, headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            "<!doctype html><title>元枢在线生图</title><h1>元枢在线生图</h1>",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/image-playground/", response_model=None)
    def yuanshu_index() -> Response:
        return index()

    @app.get("/history", response_model=None)
    def history() -> Response:
        history_path = static_path / "history.html"
        if history_path.exists():
            return FileResponse(history_path, headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            "<!doctype html><title>历史库 - 元枢在线生图</title><h1>History</h1>",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/image-playground/history", response_model=None)
    def yuanshu_history() -> Response:
        return history()

    @app.get("/sw.js", response_model=None)
    def service_worker_cleanup() -> Response:
        sw_path = static_path / "sw.js"
        if sw_path.exists():
            return FileResponse(
                sw_path,
                media_type="application/javascript",
                headers={"Cache-Control": "no-store"},
            )
        return Response("", media_type="application/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/image-playground/sw.js", response_model=None)
    def yuanshu_service_worker_cleanup() -> Response:
        return service_worker_cleanup()

    @app.get("/outputs/{filename:path}", response_model=None)
    def output_file(filename: str, request: Request) -> Response:
        return _yuanshu_owned_output_file(ctx, filename, request)

    @app.get("/inputs/{filename:path}", response_model=None)
    def input_file(filename: str) -> Response:
        if _yuanshu_public_mode_enabled():
            raise HTTPException(status_code=404, detail="Input not found")
        clean = Path(str(filename or "").strip()).name
        if not clean:
            raise HTTPException(status_code=404, detail="Input not found")
        input_path = ctx.storage.input_path(clean)
        if not input_path.is_file():
            raise HTTPException(status_code=404, detail="Input not found")
        root = ctx.storage.input_root.resolve(strict=False)
        try:
            input_path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Input not found") from exc
        return FileResponse(input_path, media_type=_guess_mime_type(input_path.name), headers={"Cache-Control": "no-store"})

    @app.get("/image-playground/outputs/{filename:path}", response_model=None)
    def yuanshu_output_file(filename: str, request: Request) -> Response:
        return _yuanshu_owned_output_file(ctx, filename, request)

    @app.get("/image-playground/inputs/{filename:path}", response_model=None)
    def yuanshu_input_file(filename: str, request: Request) -> Response:
        return _yuanshu_owned_input_file(ctx, filename, request)

    ctx.route_helpers.update(
        {
            "ensure_queue_worker_running": queue_runtime.ensure_queue_worker_running,
            "queue_channel_available": queue_runtime.queue_channel_available,
            "auth_status": lambda source: _auth_status(source, api_settings=api_settings),
            "auth_event_payload": lambda: (
                _auth_status(auth_settings.read_source(), api_settings=api_settings)
                if auth_checker is None
                else {"auth_available": bool(check_auth())}
            ),
            "queue_channels_for_source": lambda source: _queue_channels_for_source(source, api_settings=api_settings),
            "queue_max_attempts_for_channels": _queue_max_attempts_for_channels,
            "visible_running_task_ids": lambda: _visible_running_task_ids(app.state.active_task_ids, queue_storage),
            "queue_has_running_task": lambda task_id: _queue_has_running_task(queue_storage, task_id),
            "running_channel_for_task": lambda task_id: _running_channel_for_task(queue_storage, task_id),
            "with_stored_request_payload": lambda task_id, metadata: _with_stored_request_payload(storage, task_id, metadata),
            "set_task_archived": lambda task_id, archived: _set_task_archived(storage, task_id, archived),
            "mark_task_cancelled": lambda task_id: _mark_task_cancelled(storage, task_id),
            "materialize_orphaned_running_failure": lambda task_id, metadata: _materialize_orphaned_running_failure(storage, task_id, metadata),
            "apply_retry_api_provider": lambda task_id, metadata, api_provider_id=None: _apply_retry_api_provider(
                storage, task_id, metadata, api_settings, api_provider_id
            ),
            "save_uploads": lambda task_id, files, kind="input": _save_uploads(storage, task_id, files, kind=kind),
            "save_reference_assets": lambda files, request=None: _save_reference_assets(reference_asset_storage, files, request=request, ctx=ctx),
            "dedupe_reference_assets": _dedupe_reference_assets,
            "build_image_request_payload": lambda **kwargs: _build_image_request_payload(**kwargs),
            "slim_request_payload": lambda request_payload, **kwargs: _slim_request_payload(request_payload, **kwargs),
            "prompt_guard_context": lambda prompt, prompt_fidelity: _prompt_guard_context(prompt, prompt_fidelity),
            "model_prompt_for_fidelity": lambda prompt, prompt_for_model, prompt_fidelity: _model_prompt_for_fidelity(
                prompt, prompt_for_model, prompt_fidelity
            ),
            "backend_for_submit": _backend_for_submit,
            "request_api_provider_id": lambda auth_source, api_provider_id: _request_api_provider_id(
                auth_source, api_provider_id, api_settings
            ),
            "request_api_provider_name": lambda auth_source, api_provider_id: _request_api_provider_name(
                auth_source, api_provider_id, api_settings
            ),
            "request_api_mode": lambda auth_source, api_mode, api_provider_id=None: _request_api_mode(
                auth_source, api_mode, api_settings, api_provider_id
            ),
            "request_codex_mode": lambda auth_source, codex_mode=None: _request_codex_mode(
                auth_source, codex_mode, api_settings
            ),
            "request_api_images_concurrency": lambda auth_source, api_provider_id=None: _request_api_images_concurrency(
                auth_source, api_settings, api_provider_id
            ),
            "client_factory_overridden": client_factory is not None,
        }
    )
    register_webui_routes(app, ctx)

    return app


def _default_client_factory() -> CodexImageClient:
    return _client_for_auth_source(_default_auth_source())


def _default_auth_checker() -> bool:
    return bool(_auth_status(_default_auth_source())["auth_available"])


def _queue_has_running_task(queue_storage: QueueStorage, task_id: str) -> bool:
    return _running_channel_for_task(queue_storage, task_id) is not None


def _running_channel_for_task(queue_storage: QueueStorage, task_id: str) -> str | None:
    running = queue_storage.read_state()["running"]
    for channel_id, item in running.items():
        if isinstance(item, dict) and str(item.get("task_id") or "") == task_id:
            return str(channel_id)
    return None


def _visible_running_task_ids(active_task_ids: set[str], queue_storage: QueueStorage) -> set[str]:
    visible = {str(task_id) for task_id in active_task_ids}
    for item in queue_storage.read_state()["running"].values():
        if isinstance(item, dict) and item.get("task_id"):
            visible.add(str(item["task_id"]))
    return visible


def _with_stored_request_payload(storage: TaskStorage, task_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if isinstance(metadata.get("request"), dict):
        return metadata
    request_path = storage.request_path(task_id)
    try:
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return metadata
    if not isinstance(request_payload, dict):
        return metadata
    enriched = dict(metadata)
    enriched["request"] = request_payload
    return enriched


def _prompt_guard_context(prompt: str, prompt_fidelity: str) -> tuple[list[str], str]:
    mode = _normalize_prompt_fidelity(prompt_fidelity)
    if mode == "original":
        return [], build_original_prompt_instructions()
    if mode != "strict":
        return [], ""
    constraints = extract_prompt_constraints(prompt)
    return constraints, build_prompt_guard_instructions(constraints)


def _model_prompt_for_fidelity(prompt: str, prompt_for_model: str | None, prompt_fidelity: str) -> str:
    if _normalize_prompt_fidelity(prompt_fidelity) == "original":
        return prompt
    return prompt_for_model or prompt


def _build_image_request_payload(**kwargs: Any) -> dict[str, Any]:
    auth_source = str(kwargs.pop("auth_source", "auto"))
    api_mode = _normalize_api_mode(kwargs.pop("api_mode", None))
    codex_mode = _normalize_codex_mode(kwargs.pop("codex_mode", None))
    # Queued submit only needs a request preview; avoid auth/client side effects.
    if auth_source == "api":
        client_class = OpenAIResponsesImageClient if api_mode == "responses" else OpenAIImagesImageClient
        client = object.__new__(client_class)
        client.image_model = str(kwargs.get("model") or DEFAULT_IMAGE_MODEL)
        return client_class.build_payload(client, **kwargs)
    client_class = CodexImageClient if codex_mode == "responses" else CodexImagesImageClient
    client = object.__new__(client_class)
    if client_class is CodexImagesImageClient:
        client.image_model = str(kwargs.get("model") or DEFAULT_IMAGE_MODEL)
    return client_class.build_payload(client, **kwargs)


def _slim_request_payload(
    request_payload: dict[str, Any],
    *,
    input_files: list[str],
    gallery_refs: list[dict[str, Any]],
    reference_assets: list[dict[str, Any]],
    mask_file: str | None = None,
) -> dict[str, Any]:
    slim = _redact_request_image_data(request_payload)
    if isinstance(slim, dict):
        refs: dict[str, Any] = {
            "input_files": list(input_files),
            "gallery_refs": gallery_refs,
            "reference_assets": reference_assets,
        }
        if mask_file:
            refs["mask_file"] = mask_file
        slim["webui_image_refs"] = refs
    return slim if isinstance(slim, dict) else {}


def _redact_request_image_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_request_image_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_request_image_data(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return f"<redacted image data url, {len(value)} chars>"
    return value


async def _save_uploads(storage: TaskStorage, task_id: str, files: list[UploadFile], *, kind: str = "input") -> list[Path]:
    saved: list[Path] = []
    for index, upload in enumerate(files, start=1):
        data = await upload.read()
        if not data:
            continue
        if upload.content_type and not upload.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {upload.content_type}")
        saved.append(storage.write_input(task_id, upload.filename or "image.png", data, kind=kind, index=index))
    return saved


async def _save_reference_assets(
    storage: ReferenceAssetStorage,
    files: list[UploadFile],
    *,
    request: Request | None = None,
    ctx: WebUIContext | None = None,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    owner = current_yuanshu_owner_for_request(ctx, request) if ctx is not None and request is not None else None
    for upload in files:
        data = await upload.read()
        if not data:
            continue
        mime_type = _image_mime_type(upload.content_type, upload.filename or "image.png", data)
        if upload.content_type and not upload.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {upload.content_type}")
        if mime_type is None:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {upload.content_type or 'application/octet-stream'}")
        item = storage.create_or_touch(upload.filename or "image.png", data, mime_type)
        if owner is not None:
            item = storage.set_owner(str(item["id"]), owner)
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        assets.append(_reference_asset_response(item))
    return assets


def _dedupe_reference_assets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        asset_id = str(item.get("id") or "")
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        result.append(item)
    return result


def _set_task_archived(storage: TaskStorage, task_id: str, archived: bool) -> dict[str, Any]:
    metadata = storage.read_metadata(task_id)
    if archived:
        metadata["archived_at"] = str(metadata.get("archived_at") or utc_now())
    else:
        metadata.pop("archived_at", None)
    storage.write_metadata(task_id, metadata)
    return metadata


def _mark_task_cancelled(storage: TaskStorage, task_id: str) -> dict[str, Any]:
    metadata = storage.read_metadata(task_id)
    cancelled_at = utc_now()
    metadata.update(
        {
            "status": "failed",
            "updated_at": cancelled_at,
            "cancelled_at": cancelled_at,
            "cancel_requested": True,
            "error": "Task cancelled by user.",
            "last_error": "Task cancelled by user.",
        }
    )
    metadata.pop("request", None)
    storage.write_metadata(task_id, metadata)
    return metadata


def _yuanshu_owned_input_file(ctx: WebUIContext, filename: str, request: Request) -> Response:
    clean = Path(str(filename or "").strip()).name
    if not clean:
        raise HTTPException(status_code=404, detail="Input not found")
    input_path = ctx.storage.input_path(clean)
    if not input_path.is_file():
        raise HTTPException(status_code=404, detail="Input not found")
    root = ctx.storage.input_root.resolve(strict=False)
    try:
        input_path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Input not found") from exc

    normalized = input_path.name
    for metadata in ctx.storage.list_tasks():
        if not metadata_matches_current_yuanshu_owner(ctx, metadata, request):
            continue
        input_files = metadata.get("input_files") if isinstance(metadata.get("input_files"), list) else []
        mask_file = str(metadata.get("mask_file") or "")
        if normalized in {Path(str(item)).name for item in input_files if item} or normalized == Path(mask_file).name:
            return FileResponse(
                input_path,
                media_type=_guess_mime_type(input_path.name),
                headers={"Cache-Control": "private, no-store"},
            )
    raise HTTPException(status_code=404, detail="Input not found")


def _yuanshu_owned_output_file(ctx: WebUIContext, filename: str, request: Request) -> Response:
    clean = str(filename or "").strip().lstrip("/")
    if not clean:
        raise HTTPException(status_code=404, detail="Output not found")
    output_path = ctx.storage.output_path(clean)
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")
    root = ctx.storage.output_root.resolve(strict=False)
    try:
        output_path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Output not found") from exc

    normalized = ctx.storage.output_file(output_path)
    for metadata in ctx.storage.list_tasks():
        if not metadata_matches_current_yuanshu_owner(ctx, metadata, request):
            continue
        output_files = metadata.get("output_files") if isinstance(metadata.get("output_files"), list) else []
        if normalized == str(metadata.get("output_file") or "") or normalized in {str(item) for item in output_files if item}:
            return FileResponse(
                output_path,
                media_type=_guess_mime_type(output_path.name),
                headers={"Cache-Control": "private, no-store"},
            )
        outputs = metadata.get("outputs") if isinstance(metadata.get("outputs"), list) else []
        for output in outputs:
            if isinstance(output, dict) and normalized == str(output.get("file") or ""):
                return FileResponse(
                    output_path,
                    media_type=_guess_mime_type(output_path.name),
                    headers={"Cache-Control": "private, no-store"},
                )
    raise HTTPException(status_code=404, detail="Output not found")


app = create_app()
