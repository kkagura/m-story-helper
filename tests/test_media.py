import asyncio
import io
import time
from uuid import uuid4

import numpy as np
import pytest
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from fastapi.testclient import TestClient
from PIL import Image

from app.api.server import create_app
from app.config import Settings
from app.media.frames import LatestFrameBuffer, ReceivedFrame
from app.media.service import MediaFailure, MediaService, OfferRequest


class TestVideoTrack(VideoStreamTrack):
    __test__ = False

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        pixels = np.zeros((48, 64, 3), dtype=np.uint8)
        pixels[:, :, 1] = 180
        frame = VideoFrame.from_ndarray(pixels, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


def test_latest_frame_buffer_does_not_accumulate():
    buffer = LatestFrameBuffer()
    pixels = np.zeros((1, 1, 3), dtype=np.uint8)
    for frame_id in range(100):
        buffer.put(ReceivedFrame("test", frame_id, 1, 0, 0, None, 1, 1, pixels))
    assert buffer.take().frame_id == 99
    assert buffer.replaced_frames == 99
    assert buffer.peek().frame_id == 99
    assert buffer.take() is None
    buffer.clear()
    assert buffer.peek() is None


def test_invalid_offer_and_unknown_session(tmp_path):
    application = create_app(Settings(web_dist=str(tmp_path)))
    session_id = str(uuid4())
    with TestClient(application, base_url="http://127.0.0.1:8765") as client:
        response = client.post("/api/media/offer", json={
            "session_id": session_id, "type": "offer", "sdp": "not-sdp",
        })
        assert response.status_code == 400
        assert client.get("/api/status").json()["media"]["state"] == "idle"
        assert client.get(f"/api/media/{session_id}/snapshot").status_code == 404
        assert client.delete(f"/api/media/{session_id}").status_code == 204
        assert client.delete(f"/api/media/{session_id}").status_code == 204


async def connect_sender(service):
    sender = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    sender.addTransceiver(TestVideoTrack(), direction="sendonly")
    try:
        await sender.setLocalDescription(await sender.createOffer())
        request = OfferRequest(session_id=uuid4(), type="offer", sdp=sender.localDescription.sdp)
        answer = await service.negotiate(request)
        await sender.setRemoteDescription(RTCSessionDescription(sdp=answer.sdp, type=answer.type))
        return sender, request
    except BaseException:
        await sender.close()
        raise


async def wait_until(predicate, timeout=10):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


def test_receive_snapshot_single_session_and_shutdown():
    async def scenario():
        service = MediaService(Settings())
        sender = None
        try:
            sender, request = await connect_sender(service)
            await wait_until(lambda: service.status().received_frames >= 3)
            status = service.heartbeat(str(request.session_id))
            assert status.state == "receiving"
            assert (status.width, status.height) == (64, 48)
            with pytest.raises(MediaFailure) as conflict:
                await service.negotiate(request)
            assert conflict.value.status_code == 409
            payload, frame = await service.snapshot(str(request.session_id))
            image = Image.open(io.BytesIO(payload))
            assert image.size == (64, 48)
            assert image.getpixel((32, 24))[1] > 100
            assert frame.bgr.flags.writeable is False
            await service.close(str(uuid4()))
            assert service.status().state == "receiving"
            await service.shutdown()
            assert service.status().state == "closed"
            assert service.status().last_frame_id is None
            with pytest.raises(MediaFailure):
                await service.snapshot(str(request.session_id))
        finally:
            await service.shutdown()
            if sender:
                await sender.close()

    asyncio.run(scenario())


def test_no_frame_timeout_reclaims_session():
    async def scenario():
        service = MediaService(Settings(media_frame_timeout_seconds=1))
        sender = None
        try:
            sender, request = await connect_sender(service)
            await wait_until(lambda: service.status().received_frames > 0)
            # Stop producing frames while keeping the transport connected.
            sender.getSenders()[0].replaceTrack(None)
            started = time.monotonic()
            while service.status().state != "error" and time.monotonic() - started < 6:
                service.heartbeat(str(request.session_id))
                await asyncio.sleep(0.1)
            assert service.status().state == "error"
            assert service.status().reason == "视频长时间没有新帧。"
            await service.close(str(request.session_id))
        finally:
            await service.shutdown()
            if sender:
                await sender.close()

    asyncio.run(scenario())
