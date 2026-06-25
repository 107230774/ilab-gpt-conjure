from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Response

from codex_image.webui.context import WebUIContext
from codex_image.webui.yuanshu_scope import YUANSHU_SESSION_COOKIE, new_yuanshu_session_id, session_from_payload


def register_yuanshu_routes(app: FastAPI, ctx: WebUIContext) -> None:
    @app.get("/api/yuanshu/bootstrap")
    def get_yuanshu_bootstrap() -> dict[str, Any]:
        return {"yuanshu": ctx.yuanshu.public()}

    @app.post("/api/yuanshu/bootstrap")
    def update_yuanshu_bootstrap(response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            session = session_from_payload(ctx, payload)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not session.get("token") or not session.get("key_id"):
            raise HTTPException(status_code=400, detail="Yuanshu playground token is required")
        session_id = new_yuanshu_session_id()
        ctx.yuanshu_sessions[session_id] = session
        response.set_cookie(
            YUANSHU_SESSION_COOKIE,
            session_id,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/image-playground",
        )
        return {
            "yuanshu": {
                "ready": True,
                "api_base": session.get("api_base"),
                "model": session.get("model"),
                "session_token_id": session.get("session_token_id"),
                "user_id": session.get("user_id"),
                "key_id": session.get("key_id"),
                "key_name": session.get("key_name"),
                "group_id": session.get("group_id"),
                "group_name": session.get("group_name"),
                "token_expires_at": session.get("token_expires_at"),
                "session_id": session_id,
            }
        }
