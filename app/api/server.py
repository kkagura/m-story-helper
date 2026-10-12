import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.config import Settings, load_settings
from app.engine import EngineService, EngineStatus
from app.media.service import AnswerResponse, MediaFailure, MediaService, MediaStatus, OfferRequest

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__


class StatusResponse(BaseModel):
    engine: EngineStatus
    web_ui_ready: bool
    media: MediaStatus


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    engine = EngineService(capture_available=True)
    media = MediaService(settings)
    dist_path = settings.web_dist_path
    # StaticFiles is mounted at startup; build changes require a server restart.
    web_ui_ready = dist_path.is_dir() and (dist_path / "index.html").is_file()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine.start()
        logger.info("Frontend build available: %s", web_ui_ready)
        try:
            yield
        finally:
            try:
                await media.shutdown()
            finally:
                engine.stop()

    api = FastAPI(title="Maple Vision Lab", version=__version__, lifespan=lifespan)
    api.state.engine = engine
    api.state.media = media
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @api.exception_handler(MediaFailure)
    async def media_failure(_: Request, exc: MediaFailure) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @api.middleware("http")
    async def validate_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed"})
        return await call_next(request)

    @api.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @api.get("/api/status", response_model=StatusResponse)
    async def status() -> StatusResponse:
        return StatusResponse(
            engine=engine.status(), web_ui_ready=web_ui_ready, media=media.status()
        )

    @api.post("/api/media/offer", response_model=AnswerResponse)
    async def offer(body: OfferRequest) -> AnswerResponse:
        return await media.negotiate(body)

    @api.post("/api/media/{session_id}/heartbeat", response_model=MediaStatus)
    async def heartbeat(session_id: UUID) -> MediaStatus:
        return media.heartbeat(str(session_id))

    @api.delete("/api/media/{session_id}", status_code=204)
    async def close_media(session_id: UUID) -> Response:
        await media.close(str(session_id))
        return Response(status_code=204)

    @api.get("/api/media/{session_id}/snapshot")
    async def snapshot(session_id: UUID) -> Response:
        payload, frame = await media.snapshot(str(session_id))
        return Response(
            content=payload,
            media_type="image/png",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="maple-{frame.session_id}-{frame.frame_id}.png"'
                ),
                "Cache-Control": "no-store",
                "X-Frame-Id": str(frame.frame_id),
                "X-Session-Id": frame.session_id,
                "X-Size-Version": str(frame.size_version),
            },
        )

    if web_ui_ready:
        api.mount("/", StaticFiles(directory=str(dist_path), html=True), name="web")
    else:

        @api.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def frontend_not_built() -> str:
            return """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>Maple Vision Lab</title>
<body><h1>本地服务已启动</h1>
<p>前端尚未构建。请在宿主机的 web 目录运行 pnpm install 和 pnpm build，
然后重启后端；开发时也可运行 pnpm dev。</p>
<p><a href="/docs">API 文档</a> · <a href="/api/health">健康检查</a></p>
</body></html>"""

    return api
