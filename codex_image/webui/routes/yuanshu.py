from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException

from codex_image.webui.context import WebUIContext


def register_yuanshu_routes(app: FastAPI, ctx: WebUIContext) -> None:
    @app.get("/api/yuanshu/bootstrap")
    def get_yuanshu_bootstrap() -> dict[str, Any]:
        return {"yuanshu": ctx.yuanshu.public()}

    @app.post("/api/yuanshu/bootstrap")
    def update_yuanshu_bootstrap(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        ctx.yuanshu.update(payload)
        if not ctx.yuanshu.token:
            raise HTTPException(status_code=400, detail="Yuanshu playground token is required")
        return {"yuanshu": ctx.yuanshu.public()}
