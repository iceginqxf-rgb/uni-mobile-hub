"""Native Scrcpy v5.0.1 device session (no adbutils / cv2 dependency)."""

from __future__ import annotations

import logging
import os
import random
import select
import socket
import struct
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from android.scrcpy import const
from android.scrcpy.control import ScrcpyControl
from utils.logging_setup import get_logger

_log = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCRCPY_JAR = BASE_DIR / "resources" / "scrcpy" / "scrcpy-server.jar"


class ScrcpySession:
    """Manage one device's ``scrcpy-server`` process, video stream, and control channel."""

    def __init__(
        self,
        adb,
        serial: str,
        *,
        server_jar: str | Path = DEFAULT_SCRCPY_JAR,
        server_version: str = const.SCRCPY_SERVER_VERSION,
        max_width: int = 1080,
        bitrate: int = 8_000_000,
        max_fps: int = 30,
        i_frame_interval: int = 2,
        connection_timeout_ms: int = 5000,
    ) -> None:
        self.adb = adb
        self.serial = serial
        self.server_jar = Path(server_jar) if server_jar else DEFAULT_SCRCPY_JAR
        self.server_version = server_version or const.SCRCPY_SERVER_VERSION
        self.max_width = max(0, int(max_width))
        self.bitrate = max(0, int(bitrate))
        self.max_fps = max(0, int(max_fps))
        self.i_frame_interval = max(1, int(i_frame_interval or 2))
        self.connection_timeout = max(500, int(connection_timeout_ms))

        self.scid = random.randint(0, 0x7FFFFFFF)
        self.scid_hex = f"{self.scid:08x}"
        self.socket_name = f"scrcpy_{self.scid_hex}"
        self._remote_socket = f"localabstract:{self.socket_name}"

        self.alive = False
        self.control_available = False
        self.device_name: str = ""
        self.video_codec: str = ""
        self.resolution: Optional[Tuple[int, int]] = None

        self._server_proc: Optional[subprocess.Popen] = None
        self._listen_socket: Optional[socket.socket] = None
        self._video_socket: Optional[socket.socket] = None
        self.control_socket: Optional[socket.socket] = None
        self.control_socket_lock = threading.Lock()
        self.control = ScrcpyControl(self)

        self.clipboard_text: Optional[str] = None
        self.clipboard_event = threading.Event()
        self.clipboard_ack_event = threading.Event()
        self.clipboard_ack_sequence: int = const.SEQUENCE_INVALID

        self._h264_listeners: List[Callable[[bytes, int, bool, bool], None]] = []
        self._listeners_lock = threading.Lock()
        self._last_sps_nal: Optional[bytes] = None
        self._last_pps_nal: Optional[bytes] = None
        self._last_keyframe_chunk: Optional[bytes] = None

        self._stream_thread: Optional[threading.Thread] = None
        self._msg_thread: Optional[threading.Thread] = None

    def is_available(self) -> bool:
        return self.server_jar.is_file() and self.adb.is_available()

    def add_h264_listener(self, cb: Callable[[bytes, int, bool, bool], None]) -> None:
        with self._listeners_lock:
            if cb not in self._h264_listeners:
                self._h264_listeners.append(cb)

    def remove_h264_listener(self, cb: Callable[[bytes, int, bool, bool], None]) -> None:
        with self._listeners_lock:
            with suppress(ValueError):
                self._h264_listeners.remove(cb)

    def start(self, control_enabled: bool = True) -> bool:
        if self.alive:
            return True
        if not self.server_jar.is_file():
            _log.warning("scrcpy-server.jar missing at %s", self.server_jar)
            return False

        self._push_server()
        listen_port = self._open_listen_socket()
        try:
            self.adb.run(["reverse", self._remote_socket, f"tcp:{listen_port}"], serial=self.serial, timeout=6)
        except Exception as exc:  # noqa: BLE001
            _log.warning("adb reverse failed for %s: %s", self.serial, exc)
            self._close_sockets()
            return False

        if not self._launch_server(control_enabled=control_enabled):
            self.stop()
            return False

        if not self._accept_handshake(expect_control=control_enabled):
            self.stop()
            return False

        self.alive = True
        self.control_available = self.control_socket is not None
        if self.control_available:
            self._msg_thread = threading.Thread(
                target=self._device_message_loop,
                name=f"scrcpy-msg-{self.serial[:8]}",
                daemon=True,
            )
            self._msg_thread.start()

        self._stream_thread = threading.Thread(
            target=self._stream_loop,
            name=f"scrcpy-vid-{self.serial[:8]}",
            daemon=True,
        )
        self._stream_thread.start()
        return True

    def stop(self) -> None:
        self.alive = False
        proc = self._server_proc
        self._server_proc = None
        if proc is not None and proc.poll() is None:
            with suppress(OSError):
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with suppress(OSError):
                    proc.kill()
        self._close_sockets()
        with suppress(Exception):
            self.adb.run(["reverse", "--remove", self._remote_socket], serial=self.serial, timeout=4)
        with self._listeners_lock:
            self._h264_listeners.clear()

    def _open_listen_socket(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(3)
        sock.settimeout(self.connection_timeout / 1000.0)
        self._listen_socket = sock
        return int(sock.getsockname()[1])

    def _close_sockets(self) -> None:
        for attr in ("control_socket", "_video_socket", "_listen_socket"):
            sock = getattr(self, attr, None)
            setattr(self, attr, None)
            if sock is not None:
                with suppress(OSError):
                    sock.close()

    def _push_server(self) -> None:
        remote_jar = f"/data/local/tmp/{self.server_jar.name}"
        expected = self.server_jar.stat().st_size
        try:
            out = self.adb.shell(self.serial, f"wc -c < {remote_jar} 2>/dev/null || echo 0", timeout=5).strip()
            if out.isdigit() and int(out) == expected:
                return
        except Exception:  # noqa: BLE001
            pass
        res = self.adb.run(["push", str(self.server_jar), remote_jar], serial=self.serial, timeout=20, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"failed pushing scrcpy-server.jar: {(res.stderr or res.stdout or '')[:200]}")

    def _launch_server(self, *, control_enabled: bool = True) -> bool:
        commands = [
            f"CLASSPATH=/data/local/tmp/{self.server_jar.name}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            self.server_version,
            f"scid={self.scid_hex}",
            "log_level=info",
            f"max_size={self.max_width}" if self.max_width else None,
            f"max_fps={self.max_fps}" if self.max_fps else None,
            f"video_bit_rate={self.bitrate}" if self.bitrate else None,
            f"video_codec_options=i-frame-interval={self.i_frame_interval}",
            f"control={'true' if control_enabled else 'false'}",
            "audio=false",
            "clipboard_autosync=false",
        ]
        shell_str = " ".join(c for c in commands if c)
        cmd = self.adb._build_cmd(self.serial, ["shell", shell_str])
        try:
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            return True
        except OSError as exc:
            _log.warning("failed starting scrcpy-server process for %s: %s", self.serial, exc)
            return False

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        buf = bytearray()
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def _accept_handshake(self, *, expect_control: bool = True) -> bool:
        if self._listen_socket is None:
            return False
        try:
            video_sock, _ = self._listen_socket.accept()
            video_sock.settimeout(self.connection_timeout / 1000.0)
            self._video_socket = video_sock

            if expect_control:
                ctrl_sock, _ = self._listen_socket.accept()
                ctrl_sock.settimeout(1.0)
                self.control_socket = ctrl_sock

            with suppress(OSError):
                self._listen_socket.close()
            self._listen_socket = None

            return self._read_video_preamble(video_sock)
        except (OSError, socket.timeout) as exc:
            _log.warning("scrcpy handshake failed for %s: %s", self.serial, exc)
            return False

    def _read_video_preamble(self, video_sock: socket.socket) -> bool:
        dev_name = self._recv_exact(video_sock, 64)
        if not dev_name:
            return False
        self.device_name = dev_name.decode("utf-8", errors="ignore").rstrip("\x00")
        preamble = self._recv_exact(video_sock, 16)
        if len(preamble) != 16:
            return False
        self.video_codec = preamble[:4].decode("ascii", errors="ignore").strip("\x00")
        width, height = struct.unpack(">II", preamble[8:16])
        if 0 < width <= 10000 and 0 < height <= 10000:
            self.resolution = (int(width), int(height))
        video_sock.setblocking(False)
        return True

    @staticmethod
    def consume_video_packets(
        buf: bytearray,
        owner: Optional["ScrcpySession"] = None,
    ) -> Optional[List[Tuple[bytes, int, bool, bool]]]:
        """Drain complete scrcpy 12-byte-header session/media packets from ``buf``."""
        ready: List[Tuple[bytes, int, bool, bool]] = []
        while True:
            if len(buf) < const.VIDEO_HEADER_SIZE:
                return ready
            head_lo, head_hi = struct.unpack(">QI", buf[: const.VIDEO_HEADER_SIZE])
            if head_lo & const.VIDEO_FLAG_SESSION:
                new_w = head_lo & 0xFFFFFFFF
                new_h = head_hi
                if owner is not None and new_w and new_h:
                    owner.resolution = (int(new_w), int(new_h))
                del buf[: const.VIDEO_HEADER_SIZE]
                continue
            size = head_hi
            if size == 0 or size > const.VIDEO_MAX_PAYLOAD:
                buf.clear()
                return None
            if len(buf) < const.VIDEO_HEADER_SIZE + size:
                return ready
            frame_bytes = bytes(buf[const.VIDEO_HEADER_SIZE : const.VIDEO_HEADER_SIZE + size])
            del buf[: const.VIDEO_HEADER_SIZE + size]
            is_config = bool(head_lo & const.VIDEO_FLAG_CONFIG)
            is_keyframe = bool(head_lo & const.VIDEO_FLAG_KEYFRAME)
            pts_us = head_lo & const.VIDEO_PTS_MASK
            ready.append((frame_bytes, pts_us, is_keyframe, is_config))

    def _update_h264_bootstrap_cache(self, frame_bytes: bytes) -> None:
        n = len(frame_bytes)
        i = 0
        starts: List[int] = []
        while i + 3 <= n:
            if frame_bytes[i] == 0 and frame_bytes[i + 1] == 0:
                if frame_bytes[i + 2] == 1:
                    starts.append(i + 3)
                    i += 3
                    continue
                if i + 4 <= n and frame_bytes[i + 2] == 0 and frame_bytes[i + 3] == 1:
                    starts.append(i + 4)
                    i += 4
                    continue
            i += 1
        for idx, start in enumerate(starts):
            end = starts[idx + 1] - 3 if idx + 1 < len(starts) else n
            while end > start and frame_bytes[end - 1] == 0:
                end -= 1
            if end <= start:
                continue
            nal = frame_bytes[start:end]
            nal_type = nal[0] & 0x1F
            if nal_type == 7:
                self._last_sps_nal = nal
            elif nal_type == 8:
                self._last_pps_nal = nal

    def get_h264_parameter_sets(self) -> Optional[bytes]:
        if not (self._last_sps_nal and self._last_pps_nal):
            return None
        sc = b"\x00\x00\x00\x01"
        return sc + self._last_sps_nal + sc + self._last_pps_nal

    def get_h264_bootstrap(self) -> Optional[bytes]:
        params = self.get_h264_parameter_sets()
        idr = self._last_keyframe_chunk
        if not (params and idr):
            return None
        sc = b"\x00\x00\x00\x01"
        return params + (idr if idr.startswith(b"\x00\x00") else sc + idr)

    def _dispatch_packet(self, frame_bytes: bytes, pts_us: int, is_keyframe: bool, is_config: bool) -> None:
        if is_config:
            self._update_h264_bootstrap_cache(frame_bytes)
        elif is_keyframe:
            self._last_keyframe_chunk = frame_bytes
            self._update_h264_bootstrap_cache(frame_bytes)

        with self._listeners_lock:
            callbacks = list(self._h264_listeners)
        for cb in callbacks:
            try:
                cb(frame_bytes, pts_us, is_keyframe, is_config)
            except Exception as exc:  # noqa: BLE001
                _log.debug("h264 listener error on %s: %s", self.serial, exc)

    def _stream_loop(self) -> None:
        sock = self._video_socket
        if sock is None:
            return
        buf = bytearray()
        while self.alive and self._video_socket is sock:
            try:
                readable, _, _ = select.select([sock], [], [], 0.2)
                if not readable:
                    continue
                chunk = sock.recv(0x10000)
                if chunk == b"":
                    break
                buf.extend(chunk)
                ready = self.consume_video_packets(buf, self)
                if not ready:
                    continue
                for frame_bytes, pts_us, is_keyframe, is_config in ready:
                    self._dispatch_packet(frame_bytes, pts_us, is_keyframe, is_config)
            except (BlockingIOError, InterruptedError):
                continue
            except (OSError, ConnectionError):
                break
        if self.alive:
            self.stop()

    def _device_message_loop(self) -> None:
        sock = self.control_socket
        if sock is None:
            return
        while self.alive and self.control_socket is sock:
            try:
                head = self._recv_exact(sock, 1)
                if len(head) != 1:
                    if not self.alive:
                        break
                    continue
                msg_type = head[0]
                if msg_type == const.DEVICE_MSG_TYPE_CLIPBOARD:
                    len_bytes = self._recv_exact(sock, 4)
                    if len(len_bytes) != 4:
                        continue
                    (length,) = struct.unpack(">I", len_bytes)
                    payload = self._recv_exact(sock, length)
                    if len(payload) == length:
                        self.clipboard_text = payload.decode("utf-8", errors="replace")
                        self.clipboard_event.set()
                elif msg_type == const.DEVICE_MSG_TYPE_ACK_CLIPBOARD:
                    payload = self._recv_exact(sock, 8)
                    if len(payload) == 8:
                        (seq,) = struct.unpack(">Q", payload)
                        self.clipboard_ack_sequence = seq
                        self.clipboard_ack_event.set()
                elif msg_type == const.DEVICE_MSG_TYPE_UHID_OUTPUT:
                    hdr = self._recv_exact(sock, 4)
                    if len(hdr) == 4:
                        _id, sz = struct.unpack(">HH", hdr)
                        if sz > 0:
                            self._recv_exact(sock, sz)
            except socket.timeout:
                continue
            except (OSError, ConnectionError):
                break
