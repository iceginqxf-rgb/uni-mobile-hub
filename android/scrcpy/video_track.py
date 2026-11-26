"""Scrcpy H.264 WebRTC passthrough track and Socket.IO JPEG frame provider."""

from __future__ import annotations

import asyncio
import fractions
import io
import threading
import time
from collections import deque
from contextlib import suppress
from typing import Any, Deque, Optional

import av
from aiortc.mediastreams import MediaStreamTrack

from ios.screen_provider.base_provider import BaseScreenProvider
from utils.logging_setup import get_logger

_log = get_logger(__name__)

_TIME_BASE = fractions.Fraction(1, 90000)


class ScrcpyVideoTrack(MediaStreamTrack):  # type: ignore[misc]
    """Pass raw H.264 Annex-B access units from ``ScrcpySession`` directly to aiortc."""

    kind = "video"

    def __init__(self, session, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        super().__init__()
        self._session = session
        self._loop = loop
        self._queue: Optional[asyncio.Queue[Any]] = asyncio.Queue(maxsize=128) if loop is not None else None
        self._pre_loop_buf: Deque[Any] = deque(maxlen=128)
        self._lock = threading.Lock()
        self._pts_offset: Optional[int] = None
        self._last_pts: int = -1
        self._attached = False
        self._bootstrap_pushed = False
        self._stopped = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            if self._queue is None:
                self._queue = asyncio.Queue(maxsize=128)
            while self._pre_loop_buf:
                pkt = self._pre_loop_buf.popleft()
                self._enqueue(pkt)

    def start(self) -> None:
        if self._attached:
            return
        self._attached = True
        bootstrap = self._session.get_h264_bootstrap()
        if bootstrap:
            self.push_bootstrap(bootstrap)
            self._bootstrap_pushed = True
        self._session.add_h264_listener(self._on_h264)

    def _on_h264(self, frame_bytes: bytes, pts_us: int, is_keyframe: bool, is_config: bool) -> None:
        if self._stopped or is_config or pts_us == 0:
            return
        payload = frame_bytes
        if is_keyframe:
            params = self._session.get_h264_parameter_sets()
            if params and not payload.startswith(params):
                payload = params + payload
            if not self._bootstrap_pushed:
                self._bootstrap_pushed = True
        self.push_frame(payload, pts_us, is_keyframe)

    def push_bootstrap(self, annexb: bytes) -> None:
        if not annexb:
            return
        pkt = self._build_packet(annexb, pts_90khz=0)
        if pkt is not None:
            self._dispatch_packet(pkt)

    def push_frame(self, annexb: bytes, pts_us: int, _is_keyframe: bool) -> None:
        if not annexb or pts_us == 0:
            return
        with self._lock:
            if self._pts_offset is None:
                self._pts_offset = pts_us
            pts_90khz = int((pts_us - self._pts_offset) * 90 / 1000)
            if pts_90khz <= 0:
                pts_90khz = 1
            if pts_90khz <= self._last_pts:
                pts_90khz = self._last_pts + 1
            self._last_pts = pts_90khz
        pkt = self._build_packet(annexb, pts_90khz=pts_90khz)
        if pkt is not None:
            self._dispatch_packet(pkt)

    def _dispatch_packet(self, packet: Any) -> None:
        with self._lock:
            loop = self._loop
            if loop is None:
                self._pre_loop_buf.append(packet)
                return
        try:
            loop.call_soon_threadsafe(self._enqueue, packet)
        except RuntimeError:
            pass

    @staticmethod
    def _build_packet(annexb: bytes, *, pts_90khz: int) -> Optional[Any]:
        try:
            packet = av.Packet(annexb)
        except Exception as exc:  # noqa: BLE001
            _log.debug("av.Packet failed: %s", exc)
            return None
        packet.pts = pts_90khz
        packet.time_base = _TIME_BASE
        return packet

    def _enqueue(self, packet: Any) -> None:
        q = self._queue
        if q is None:
            return
        if q.full():
            with suppress(asyncio.QueueEmpty):
                q.get_nowait()
        with suppress(asyncio.QueueFull):
            q.put_nowait(packet)

    async def recv(self):  # type: ignore[override]
        if self._loop is None:
            self.bind_loop(asyncio.get_running_loop())
        assert self._queue is not None
        return await self._queue.get()

    def stop(self) -> None:
        self._stopped = True
        if self._attached:
            self._attached = False
            with suppress(Exception):
                self._session.remove_h264_listener(self._on_h264)
        super().stop()


class ScrcpyFrameProvider(BaseScreenProvider):
    """Decode Scrcpy H.264 access units to JPEG frames for Socket.IO ``StreamSession``."""

    name = "scrcpy"

    def __init__(self, session, quality: int = 70) -> None:
        self.session = session
        self.quality = max(25, min(95, int(quality)))
        self._codec = av.codec.CodecContext.create("h264", "r")
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._new_frame = threading.Event()
        self._running = False
        self._healthy = False
        self._frames = 0
        self._decodable = False

    def start(self) -> None:
        if self._running:
            return
        if not self.session.alive and not self.session.start():
            raise RuntimeError(f"scrcpy session failed to start for {self.session.serial}")
        self._running = True
        self._healthy = True
        bootstrap = self.session.get_h264_bootstrap()
        if bootstrap:
            self._decode_and_store(bootstrap)
        self.session.add_h264_listener(self._on_h264)

    def _on_h264(self, frame_bytes: bytes, pts_us: int, is_keyframe: bool, is_config: bool) -> None:
        if not self._running or is_config:
            return
        payload = frame_bytes
        if is_keyframe:
            params = self.session.get_h264_parameter_sets()
            if params and not payload.startswith(params):
                payload = params + payload
            self._decodable = True
        elif not self._decodable:
            return
        self._decode_and_store(payload)

    def _decode_and_store(self, annexb: bytes) -> None:
        try:
            with self._lock:
                frames = self._codec.decode(av.Packet(annexb))
            if not frames:
                return
            img = frames[-1].to_image()
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.quality)
            with self._lock:
                self._latest_jpeg = buf.getvalue()
                self._frames += 1
                self._healthy = True
                self._decodable = True
            self._new_frame.set()
        except Exception:  # noqa: BLE001
            pass

    def read_frame(self) -> Optional[bytes]:
        if not self._running:
            return None
        self._new_frame.wait(timeout=0.5)
        self._new_frame.clear()
        with self._lock:
            self._healthy = bool(self.session.alive)
            return self._latest_jpeg

    def stop(self) -> None:
        self._running = False
        self._healthy = False
        with suppress(Exception):
            self.session.remove_h264_listener(self._on_h264)
        self._new_frame.set()

    def health(self) -> bool:
        return self._running and bool(self.session.alive) and self._healthy

    def get_frame_size(self):
        return getattr(self.session, "resolution", None)

    @property
    def stats(self) -> dict:
        return {"provider": self.name, "frames": self._frames, "healthy": self.health()}
