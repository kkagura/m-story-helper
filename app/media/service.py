import asyncio
import io
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.media.frames import LatestFrameBuffer, ReceivedFrame

logger = logging.getLogger(__name__)


class MediaFailure(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class OfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    type: Literal["offer"]
    sdp: str = Field(min_length=1, max_length=131_072)


class AnswerResponse(BaseModel):
    session_id: str
    type: Literal["answer"] = "answer"
    sdp: str


class MediaStatus(BaseModel):
    session_id: str | None = None
    state: Literal["idle", "negotiating", "connecting", "receiving", "closed", "error"] = "idle"
    connection_state: str = "new"
    received_frames: int = 0
    receive_fps: float = 0
    replaced_frames: int = 0
    width: int = 0
    height: int = 0
    size_version: int = 0
    last_frame_id: int | None = None
    last_frame_age_ms: float | None = None
    conversion_ms: float | None = None
    reason: str | None = None


@dataclass
class MediaSession:
    id: str
    pc: RTCPeerConnection
    buffer: LatestFrameBuffer = field(default_factory=LatestFrameBuffer)
    state: str = "negotiating"
    reason: str | None = None
    negotiated_at: float | None = None
    last_control_at: float = field(default_factory=time.monotonic)
    last_frame_at: float | None = None
    first_frame_at: float | None = None
    received_frames: int = 0
    width: int = 0
    height: int = 0
    size_version: int = 0
    frame_times: deque = field(default_factory=lambda: deque(maxlen=600))
    receiver: asyncio.Task | None = None
    watchdog: asyncio.Task | None = None
    close_task: asyncio.Task | None = None
    closing: bool = False

    def status(self) -> MediaStatus:
        now = time.monotonic()
        while self.frame_times and self.frame_times[0] < now - 2:
            self.frame_times.popleft()
        elapsed = min(now - self.first_frame_at, 2) if self.first_frame_at is not None else 0
        latest = self.buffer.peek()
        return MediaStatus(
            session_id=self.id,
            state=self.state,
            connection_state=self.pc.connectionState,
            received_frames=self.received_frames,
            receive_fps=(
                round(len(self.frame_times) / elapsed, 2)
                if elapsed >= 0.5 and not self.closing else 0
            ),
            replaced_frames=self.buffer.replaced_frames,
            width=self.width,
            height=self.height,
            size_version=self.size_version,
            last_frame_id=latest.frame_id if latest else None,
            last_frame_age_ms=(
                round((now - latest.received_at_monotonic) * 1000, 2) if latest else None
            ),
            conversion_ms=(
                round((latest.converted_at_monotonic - latest.received_at_monotonic) * 1000, 2)
                if latest else None
            ),
            reason=self.reason,
        )


class MediaService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: MediaSession | None = None
        self._last_status = MediaStatus()
        self._accepting = True
        self._lock = asyncio.Lock()
        self._snapshot_task: asyncio.Task | None = None

    def status(self) -> MediaStatus:
        return self._session.status() if self._session else self._last_status.model_copy()

    def _require_session(self, session_id: str) -> MediaSession:
        session = self._session
        if session is None or session.id != session_id:
            raise MediaFailure(404, "媒体会话不存在，请重新连接。")
        if session.closing:
            raise MediaFailure(410, session.reason or "媒体会话已经关闭。")
        return session

    async def negotiate(self, request: OfferRequest) -> AnswerResponse:
        media_lines = [line for line in request.sdp.splitlines() if line.startswith("m=")]
        if len(media_lines) != 1 or not media_lines[0].startswith("m=video "):
            raise MediaFailure(400, "只接受一个视频轨道，不接受音频或数据通道。")
        async with self._lock:
            if not self._accepting:
                raise MediaFailure(503, "服务正在关闭。")
            if self._session is not None:
                raise MediaFailure(409, "已有媒体会话，请先停止原会话后再连接。")
            session = MediaSession(
                id=str(request.session_id),
                pc=RTCPeerConnection(RTCConfiguration(iceServers=[])),
            )
            self._session = session

        @session.pc.on("track")
        def on_track(track):
            if track.kind != "video" or session.receiver is not None or session.closing:
                track.stop()
                return
            session.receiver = asyncio.create_task(self._receive(session, track))

        @session.pc.on("connectionstatechange")
        async def connection_changed():
            if session.pc.connectionState in ("failed", "closed") and not session.closing:
                await self._close(session, "媒体连接已关闭或失败。", error=True)

        try:
            async with asyncio.timeout(self.settings.media_negotiation_timeout_seconds):
                await session.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=request.sdp, type=request.type)
                )
                if session.receiver is None:
                    raise ValueError("远端没有可接收的视频轨道")
                for transceiver in session.pc.getTransceivers():
                    transceiver.direction = "recvonly"
                await session.pc.setLocalDescription(await session.pc.createAnswer())
            if session.closing:
                raise MediaFailure(410, "协商期间会话已被关闭。")
            session.negotiated_at = time.monotonic()
            session.last_control_at = session.negotiated_at
            session.state = "connecting" if session.received_frames == 0 else "receiving"
            session.watchdog = asyncio.create_task(self._watch(session))
            answer = session.pc.localDescription
            if answer is None:
                raise ValueError("无法创建协商应答")
            logger.info("Media session %s negotiated", session.id)
            return AnswerResponse(session_id=session.id, sdp=answer.sdp)
        except BaseException as exc:
            await self._close(session, "视频协商失败或超时。", error=True)
            if isinstance(exc, (asyncio.CancelledError, MediaFailure)):
                raise
            if isinstance(exc, TimeoutError):
                raise MediaFailure(504, "视频协商超时，请重新连接。") from exc
            logger.warning("Media negotiation failed (%s)", type(exc).__name__)
            raise MediaFailure(400, "无法协商视频，请确认发送一个有效视频轨道。") from exc

    async def _receive(self, session: MediaSession, track) -> None:
        try:
            while not session.closing:
                frame = await track.recv()
                received_at = time.monotonic()
                if frame.width * frame.height > self.settings.media_max_frame_pixels:
                    raise ValueError("Frame exceeds configured pixel limit")
                # One conversion at a time; no per-frame task queue and no inference here.
                bgr = await asyncio.to_thread(frame.to_ndarray, format="bgr24")
                bgr.flags.writeable = False
                if session.closing:
                    return
                if (frame.width, frame.height) != (session.width, session.height):
                    session.width, session.height = frame.width, frame.height
                    session.size_version += 1
                    session.buffer.clear()
                session.received_frames += 1
                converted_at = time.monotonic()
                session.first_frame_at = session.first_frame_at or received_at
                session.last_frame_at = received_at
                session.frame_times.append(converted_at)
                timestamp = (
                    float(frame.pts * frame.time_base) * 1000
                    if frame.pts is not None and frame.time_base is not None else None
                )
                session.buffer.put(
                    ReceivedFrame(
                        session_id=session.id,
                        frame_id=session.received_frames,
                        size_version=session.size_version,
                        received_at_monotonic=received_at,
                        converted_at_monotonic=converted_at,
                        media_timestamp_ms=timestamp,
                        width=frame.width,
                        height=frame.height,
                        bgr=bgr,
                    )
                )
                session.state = "receiving"
        except asyncio.CancelledError:
            raise
        except MediaStreamError:
            await self._close(session, "视频轨道已结束。")
        except Exception as exc:
            logger.warning("Media receiver failed (%s)", type(exc).__name__)
            await self._close(session, "视频解码或画面大小检查失败。", error=True)

    async def _watch(self, session: MediaSession) -> None:
        while not session.closing:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            reason = None
            if now - session.last_control_at > self.settings.media_heartbeat_timeout_seconds:
                reason = "页面控制心跳超时。"
            elif session.last_frame_at is None:
                if now - session.negotiated_at > self.settings.media_connect_timeout_seconds:
                    reason = "连接后未收到首帧。"
            elif now - session.last_frame_at > self.settings.media_frame_timeout_seconds:
                reason = "视频长时间没有新帧。"
            if reason:
                await self._close(session, reason, error=True)
                return

    def heartbeat(self, session_id: str) -> MediaStatus:
        if self._session is None and self._last_status.session_id == session_id:
            return self._last_status.model_copy()
        session = self._require_session(session_id)
        session.last_control_at = time.monotonic()
        return session.status()

    async def close(self, session_id: str) -> None:
        session = self._session
        if session is not None and session.id == session_id:
            await self._close(session, "用户停止共享。")

    async def _close(self, session: MediaSession, reason: str, *, error: bool = False) -> None:
        if session.close_task is None:
            session.closing = True
            session.state = "error" if error else "closed"
            session.reason = reason
            session.buffer.clear()
            # Cleanup must outlive cancellation of the HTTP/receiver caller.
            session.close_task = asyncio.create_task(self._cleanup(session))
        await asyncio.shield(session.close_task)

    async def _cleanup(self, session: MediaSession) -> None:
        try:
            tasks = [task for task in (session.receiver, session.watchdog) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            session.pc.remove_all_listeners()
            await session.pc.close()
        finally:
            session.buffer.clear()
            self._last_status = session.status()
            if self._session is session:
                self._session = None
            logger.info("Media session %s closed: %s", session.id, session.reason)

    async def shutdown(self) -> None:
        self._accepting = False
        if self._session is not None:
            await self._close(self._session, "本地服务退出。")
        if self._snapshot_task is not None:
            await asyncio.gather(self._snapshot_task, return_exceptions=True)

    async def snapshot(self, session_id: str) -> tuple[bytes, ReceivedFrame]:
        if self._snapshot_task is not None and not self._snapshot_task.done():
            raise MediaFailure(429, "已有截图正在编码，请稍后重试。")
        task = asyncio.create_task(self._snapshot(session_id))
        self._snapshot_task = task

        def finished(completed):
            if self._snapshot_task is completed:
                self._snapshot_task = None
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _snapshot(self, session_id: str) -> tuple[bytes, ReceivedFrame]:
        session = self._require_session(session_id)
        frame = session.buffer.peek()
        if frame is None:
            raise MediaFailure(409, "尚未收到可保存的画面。")
        age = time.monotonic() - frame.received_at_monotonic
        if age > self.settings.media_frame_timeout_seconds:
            raise MediaFailure(409, "当前画面已过期，请等待新帧或重新连接。")

        def encode() -> bytes:
            image = Image.fromarray(frame.bgr[:, :, ::-1].copy())
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        payload = await asyncio.to_thread(encode)
        current = self._require_session(session_id)
        if current is not session or session.size_version != frame.size_version:
            raise MediaFailure(409, "画面尺寸已变化，请重新保存。")
        age_after_encoding = time.monotonic() - frame.received_at_monotonic
        if age_after_encoding > self.settings.media_frame_timeout_seconds:
            raise MediaFailure(409, "截图编码期间画面已过期，请重试。")
        return payload, frame
