"""Tests for Hub-side same-origin Scrcpy WebRTC signaling relay (Issue #11)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
from flask import Flask

from api.streams_api import bp as streams_bp
from nodes.node_config import RemoteNodeConfig
from nodes.remote_node_adapter import RemoteNodeAdapter
from nodes.scrcpy_webrtc_relay import ScrcpyWebRTCRelay
from services.runtime_state import state


class _FakeSioClient:
    def __init__(self, http_session):
        self.http_session = http_session
        self.handlers = {}
        self.connected_args = None
        self.emitted = []
        self.disconnected = False

    def on(self, event):
        def _deco(fn):
            self.handlers[event] = fn
            return fn
        return _deco

    def connect(self, url, **kwargs):
        self.connected_args = (url, kwargs)

    def emit(self, event, data):
        self.emitted.append((event, data))

    def disconnect(self):
        self.disconnected = True


class TestScrcpyWebRTCRelay(unittest.TestCase):
    def setUp(self):
        self._prev = dict(state.devices)
        state.devices.clear()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"ok": True}, headers={"Set-Cookie": "rog_sess=abc123; Path=/"})
            if request.url.path == "/api/devices":
                return httpx.Response(200, json={"devices": ["DEV1"], "names": {"DEV1": "Phone1"}, "geometry": {}})
            if request.url.path in ("/api/reservations", "/api/start"):
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/api/rtc-config":
                return httpx.Response(
                    200,
                    json={"iceTransportPolicy": "relay", "iceServers": [{"urls": "turn:10.0.0.1:8012?transport=tcp"}]},
                )
            return httpx.Response(404)

        cfg = RemoteNodeConfig(id="rog", url="http://127.0.0.1:18002", type="scrcpy", username="u", password="p")
        self.adapter = RemoteNodeAdapter({}, cfg, transport=httpx.MockTransport(handler))
        self.adapter.discover()
        self.udid = self.adapter.discover()[0].udid

    def tearDown(self):
        state.devices.clear()
        state.devices.update(self._prev)

    def test_relay_forwards_offer_answer_ice_and_teardown(self):
        relay = ScrcpyWebRTCRelay()
        clients = []
        emitted_to_browser = []

        def factory(sess):
            self.assertFalse(sess.trust_env)
            c = _FakeSioClient(sess)
            clients.append(c)
            return c

        with patch("nodes.scrcpy_webrtc_relay.get_adapter", return_value=self.adapter):
            relay.start_offer(
                "sid-1",
                self.udid,
                "v=0-offer",
                lambda ev, payload: emitted_to_browser.append((ev, payload)),
                client_factory=factory,
            )

        self.assertEqual(len(clients), 1)
        c = clients[0]
        url, kwargs = c.connected_args
        self.assertEqual(url, "http://127.0.0.1:18002")
        self.assertEqual(kwargs["headers"]["Origin"], "http://127.0.0.1:18002")
        self.assertIn("rog_sess=abc123", kwargs["headers"]["Cookie"])
        self.assertEqual(c.emitted[0], ("webrtc:offer", {"device_id": "DEV1", "sdp": "v=0-offer"}))

        # Browser ICE -> upstream
        self.assertTrue(relay.send_ice("sid-1", self.udid, "cand-1", "0", 0))
        self.assertEqual(
            c.emitted[1],
            ("webrtc:ice", {"device_id": "DEV1", "candidate": "cand-1", "sdpMid": "0", "sdpMLineIndex": 0}),
        )

        # Upstream answer & ICE -> browser
        c.handlers["webrtc:answer"]({"device_id": "DEV1", "sdp": "v=0-ans", "type": "answer"})
        c.handlers["webrtc:ice"]({"device_id": "DEV1", "candidate": "srv-cand", "sdpMid": "0", "sdpMLineIndex": 0})
        self.assertEqual(emitted_to_browser[0], ("scrcpy:webrtc:answer", {"udid": self.udid, "sdp": "v=0-ans", "type": "answer"}))
        self.assertEqual(emitted_to_browser[1], ("scrcpy:webrtc:ice", {"udid": self.udid, "candidate": "srv-cand", "sdpMid": "0", "sdpMLineIndex": 0}))

        # Close sid cleans up upstream
        relay.close_sid("sid-1")
        self.assertIn(("webrtc:close", {"device_id": "DEV1"}), c.emitted)
        self.assertTrue(c.disconnected)

    def test_rtc_config_proxy_and_unavailable_retry(self):
        app = Flask(__name__)
        app.register_blueprint(streams_bp)
        with patch("api.streams_api.get_adapter", return_value=self.adapter):
            with app.test_client() as client:
                r = client.get(f"/api/devices/{self.udid}/rtc-config")
                self.assertEqual(r.status_code, 200)
                data = r.get_json()["data"]
                self.assertEqual(data["iceTransportPolicy"], "relay")
                self.assertEqual(data["iceServers"][0]["urls"], "turn:10.0.0.1:8012?transport=tcp")

        relay = ScrcpyWebRTCRelay()
        clients = []
        emitted = []

        def factory(sess):
            c = _FakeSioClient(sess)
            clients.append(c)
            return c

        with (
            patch("nodes.scrcpy_webrtc_relay.get_adapter", return_value=self.adapter),
            patch("nodes.scrcpy_webrtc_relay.time.sleep", return_value=None),
        ):
            relay.start_offer("sid-2", self.udid, "offer-1", lambda e, p: emitted.append((e, p)), client_factory=factory)
            c = clients[0]
            # First device_unavailable triggers one automatic re-offer instead of closing browser
            c.handlers["webrtc:closed"]({"device_id": "DEV1", "reason": "device_unavailable"})
            offer_count = sum(1 for ev, _ in c.emitted if ev == "webrtc:offer")
            self.assertEqual(offer_count, 2)
            self.assertEqual(emitted, [])
            # Second close forwards to browser cleanly
            c.handlers["webrtc:closed"]({"device_id": "DEV1", "reason": "device_unavailable"})
            self.assertEqual(emitted[0], ("scrcpy:webrtc:closed", {"udid": self.udid, "reason": "device_unavailable"}))

    def test_closed_old_session_does_not_emit_stale_closed_to_new_offer(self):
        relay = ScrcpyWebRTCRelay()
        clients = []
        emitted = []

        def factory(sess):
            c = _FakeSioClient(sess)
            clients.append(c)
            return c

        with patch("nodes.scrcpy_webrtc_relay.get_adapter", return_value=self.adapter):
            relay.start_offer(
                "sid-3",
                self.udid,
                "offer-1",
                lambda e, p: emitted.append((e, p)),
                offer_id="o1",
                client_factory=factory,
            )
            relay.start_offer(
                "sid-3",
                self.udid,
                "offer-2",
                lambda e, p: emitted.append((e, p)),
                offer_id="o2",
                client_factory=factory,
            )

        c1, c2 = clients
        self.assertTrue(c1.disconnected)
        # Old torn-down client fires late close -> must be ignored cleanly
        c1.handlers["webrtc:closed"]({"device_id": "DEV1", "reason": "closed"})
        self.assertEqual(emitted, [])

        # New active session forwards answer with matching offer_id
        c2.handlers["webrtc:answer"]({"device_id": "DEV1", "sdp": "ans-2", "type": "answer"})
        self.assertEqual(
            emitted,
            [("scrcpy:webrtc:answer", {"udid": self.udid, "sdp": "ans-2", "type": "answer", "offer_id": "o2"})],
        )
