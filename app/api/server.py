import asyncio
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
from app.capture.images import Screenshot, decode_screenshot
from app.config import Settings, load_settings
from app.engine import EngineService, EngineStatus
from app.media.service import AnswerResponse, MediaFailure, MediaService, MediaStatus, OfferRequest
from app.vision.models import ObservationResult, VisionFailure, VisionProfile

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
    engine = EngineService(capture_available=True, profile_path=settings.vision_profile_path)
    media = MediaService(settings)
    imported: Screenshot | None = None
    upload_lock = asyncio.Lock()
    dist_path = settings.web_dist_path
    # StaticFiles is mounted at startup; build changes require a server restart.
    web_ui_ready = dist_path.is_dir() and (dist_path / "index.html").is_file()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal imported
        engine.start()
        logger.info("Frontend build available: %s", web_ui_ready)
        try:
            yield
        finally:
            try:
                await media.shutdown()
                await engine.close_jobs()
            finally:
                imported = None
                engine.stop()

    api = FastAPI(title="Maple Vision Lab", version=__version__, lifespan=lifespan)
    api.state.engine = engine
    api.state.media = media
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @api.exception_handler(MediaFailure)
    async def media_failure(_: Request, exc: MediaFailure) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @api.exception_handler(VisionFailure)
    async def vision_failure(_: Request, exc: VisionFailure) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    def get_image(image_id: UUID) -> Screenshot:
        if imported is None or imported.frame.session_id != str(image_id):
            raise VisionFailure(404, "图片不存在或已被新图片替换，请重新上传。")
        return imported

    @api.post("/api/images", status_code=201)
    async def upload_image(request: Request):
        nonlocal imported
        if upload_lock.locked():
            raise VisionFailure(429, "已有图片正在导入，请稍后重试。")
        async with upload_lock:
            payload = bytearray()
            try:
                async with asyncio.timeout(15):
                    async for chunk in request.stream():
                        if len(payload) + len(chunk) > settings.image_max_upload_bytes:
                            raise VisionFailure(413, "文件超过上传大小上限。")
                        payload.extend(chunk)
            except TimeoutError as exc:
                raise VisionFailure(408, "上传超时，请重新选择图片。") from exc
            task = asyncio.create_task(
                asyncio.to_thread(
                    decode_screenshot, bytes(payload), settings.media_max_frame_pixels
                )
            )
            try:
                imported = await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            frame = imported.frame
            return {"image_id": frame.session_id, "width": frame.width, "height": frame.height}

    @api.get("/api/images/{image_id}/preview")
    async def image_preview(image_id: UUID) -> Response:
        image = get_image(image_id)
        return Response(
            image.preview_png, media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    @api.delete("/api/images/{image_id}", status_code=204)
    async def close_image(image_id: UUID) -> Response:
        nonlocal imported
        if imported is not None and imported.frame.session_id == str(image_id):
            imported = None
        return Response(status_code=204)

    @api.get("/api/vision/profile", response_model=VisionProfile)
    async def get_profile() -> VisionProfile:
        return engine.profile

    @api.put("/api/vision/profile", response_model=VisionProfile)
    async def put_profile(profile: VisionProfile) -> VisionProfile:
        if profile.reference_size[0] * profile.reference_size[1] > settings.media_max_frame_pixels:
            raise VisionFailure(413, "参考画面尺寸超过上限。")
        await engine.save_profile(profile)
        return profile

    @api.post("/api/images/{image_id}/analyze", response_model=ObservationResult)
    async def analyze_image(image_id: UUID, profile: VisionProfile) -> ObservationResult:
        image = get_image(image_id)
        observation = await engine.analyze(image.frame, profile)
        if get_image(image_id) is not image:
            raise VisionFailure(409, "图片在识别期间发生变化，请重试。")
        return observation.result

    @api.post("/api/media/{session_id}/analyze", response_model=ObservationResult)
    async def analyze_video(session_id: UUID, profile: VisionProfile) -> ObservationResult:
        frame = media.analysis_frame(str(session_id))
        observation = await engine.analyze(frame, profile)
        media.validate_analysis_frame(frame)
        return observation.result

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
