"""Unit tests for Scrcpy binary control, video packet parser, VideoTrack, and adapter fallback."""

from __future__ import annotations

import asyncio
import socket
import struct
import time

import av
import pytest

from android.android_adapter import AndroidAdapter
from android.device_models import AndroidDevice
from android.scrcpy import const
from android.scrcpy.control import ScrcpyControl
from android.scrcpy.session import ScrcpySession
from android.scrcpy.video_track import ScrcpyFrameProvider, ScrcpyVideoTrack
from android.screen_provider import AdbScreenshotProvider
from services.runtime_state import state


@pytest.fixture(autouse=True)
def _clean_state():
    state.devices.clear()
    state.controllers.clear()
    state.streams.clear()
    yield
    state.devices.clear()
    state.controllers.clear()
    state.streams.clear()


class _FakeParent:
    def __init__(self, sock=None):
        self.control_socket = sock
        import threading

        self.control_socket_lock = threading.Lock()
        self.resolution = (1080, 2400)
        self.clipboard_event = threading.Event()
        self.clipboard_ack_event = threading.Event()
        self.clipboard_ack_sequence = 0


def test_scrcpy_control_packet_encodings():
    ctrl = ScrcpyControl(_FakeParent())

    t_pkt = ctrl.touch(540, 1200, const.ACTION_DOWN)
    assert t_pkt[0] == const.TYPE_INJECT_TOUCH_EVENT
    assert len(t_pkt) == 32

    k_pkt = ctrl.keycode(const.KEYCODE_BACK, const.ACTION_DOWN)
    assert k_pkt == struct.pack(">BBiii", const.TYPE_INJECT_KEYCODE, const.ACTION_DOWN, const.KEYCODE_BACK, 0, 0)

    txt_pkt = ctrl.text("你好")
    raw = "你好".encode("utf-8")
    assert txt_pkt == struct.pack(">Bi", const.TYPE_INJECT_TEXT, len(raw)) + raw

    scr_pkt = ctrl.scroll(500, 1000, 0, 600)
    assert scr_pkt[0] == const.TYPE_INJECT_SCROLL_EVENT
    assert len(scr_pkt) == 21

    rst_pkt = ctrl.reset_video()
    assert rst_pkt == struct.pack(">B", const.TYPE_RESET_VIDEO)

    left, right = socket.socketpair()
    try:
        live_ctrl = ScrcpyControl(_FakeParent(sock=left))
        live_ctrl.swipe(100, 200, 300, 600, duration_ms=40)
        data = right.recv(4096)
        # At least down + moves + up packets (32B each) sent over control_socket
        assert len(data) >= 32 * 10
    finally:
        left.close()
        right.close()


def test_scrcpy_session_preamble_packets_and_bootstrap():
    class _DummyAdb:
        def is_available(self):
            return False

    sess = ScrcpySession(_DummyAdb(), "dev-scrcpy")

    # Verify 16-byte video preamble over socketpair
    srv, cli = socket.socketpair()
    try:
        cli.sendall(b"Redmi_K30_Pro".ljust(64, b"\x00"))
        cli.sendall(b"h264" + struct.pack(">B3sII", 0x80, b"\x00\x00\x00", 1080, 2400))
        assert sess._read_video_preamble(srv) is True
        assert sess.device_name == "Redmi_K30_Pro"
        assert sess.video_codec == "h264"
        assert sess.resolution == (1080, 2400)
    finally:
        srv.close()
        cli.close()

    # Verify session packet + config SPS/PPS + IDR + P-frame parsing & bootstrap cache
    sps = b"\x00\x00\x00\x01\x67\x42\x00\x1f"
    pps = b"\x00\x00\x00\x01\x68\xce\x3c\x80"
    cfg_payload = sps + pps
    idr_payload = b"\x00\x00\x00\x01\x65\x88\x84"
    p_payload = b"\x00\x00\x00\x01\x41\x9a\x10"

    buf = bytearray()
    # Session resize packet (MSB=1)
    buf.extend(struct.pack(">QI", const.VIDEO_FLAG_SESSION | 2400, 1080))
    # Config packet (PTS=0, flag=CONFIG)
    buf.extend(struct.pack(">QI", const.VIDEO_FLAG_CONFIG | 0, len(cfg_payload)) + cfg_payload)
    # Keyframe packet (PTS=1000, flag=KEYFRAME)
    buf.extend(struct.pack(">QI", const.VIDEO_FLAG_KEYFRAME | 1000, len(idr_payload)) + idr_payload)
    # P-frame (PTS=17000)
    buf.extend(struct.pack(">QI", 17000, len(p_payload)) + p_payload)

    packets = ScrcpySession.consume_video_packets(buf, owner=sess)
    assert packets is not None
    assert len(packets) == 3
    assert sess.resolution == (2400, 1080)
    assert len(buf) == 0

    for payload, pts, is_kf, is_cfg in packets:
        sess._dispatch_packet(payload, pts, is_kf, is_cfg)

    boot = sess.get_h264_bootstrap()
    assert boot == sps + pps + idr_payload


def test_scrcpy_video_track_bootstrap_first_and_monotonic_pts():
    class _StubSess:
        def __init__(self):
            self.listeners = []

        def get_h264_bootstrap(self):
            return b"\x00\x00\x00\x01\x67\x42\x00\x1f\x00\x00\x00\x01\x68\xce\x00\x00\x00\x01\x65\x88"

        def get_h264_parameter_sets(self):
            return b"\x00\x00\x00\x01\x67\x42\x00\x1f\x00\x00\x00\x01\x68\xce"

        def add_h264_listener(self, cb):
            self.listeners.append(cb)

        def remove_h264_listener(self, cb):
            if cb in self.listeners:
                self.listeners.remove(cb)

    async def _run():
        sess = _StubSess()
        track = ScrcpyVideoTrack(sess, loop=asyncio.get_running_loop())
        track.start()
        # Simulate config packet (pts=0 -> ignored), then two live frames
        track._on_h264(b"\x00\x00\x00\x01\x67\x42", 0, False, True)
        track._on_h264(b"\x00\x00\x00\x01\x41\x9a", 10_000_000, False, False)
        track._on_h264(b"\x00\x00\x00\x01\x41\x9b", 10_005_000, False, False)
        await asyncio.sleep(0.02)

        p0 = await track.recv()
        p1 = await track.recv()
        p2 = await track.recv()
        assert p0.pts == 0
        assert p1.pts >= 1
        assert p2.pts > p1.pts
        track.stop()
        assert sess.listeners == []

    asyncio.run(_run())


def test_android_adapter_falls_back_when_scrcpy_jar_missing(monkeypatch):
    monkeypatch.setattr("android.adb_client.shutil.which", lambda name: "/usr/bin/adb" if name == "adb" else None)
    adapter = AndroidAdapter({"ANDROID_USE_SCRCPY": "1", "SCRCPY_SERVER_PATH": "/nonexistent/scrcpy-server.jar"})
    monkeypatch.setattr(adapter.adb, "get_screen_size", lambda _s: (1080, 2400))
    monkeypatch.setattr(adapter.adb, "get_orientation", lambda _s: "PORTRAIT")
    state.upsert_device(AndroidDevice(udid="and-fb", name="Phone"))

    dev = adapter.connect("and-fb")
    assert dev.connected is True
    provider = adapter.make_screen_provider("and-fb", "scrcpy")
    assert isinstance(provider, AdbScreenshotProvider)
    assert provider.health() is False
    fp = ScrcpyFrameProvider(type("_S", (), {"alive": False, "resolution": (1080, 2400)})())
    assert fp.get_frame_size() == (1080, 2400)
    assert adapter.make_webrtc_track("and-fb") is None
    adapter.disconnect("and-fb")
