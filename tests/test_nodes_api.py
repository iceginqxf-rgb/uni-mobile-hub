"""Tests for Issue #13: /api/nodes health telemetry, stream stats, and backoff reconnect."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import httpx
from flask import Flask

from api.nodes_api import bp as nodes_bp
from nodes.node_config import RemoteNodeConfig
from nodes.remote_node_adapter import RemoteNodeAdapter
from nodes.scrcpy_webrtc_relay import scrcpy_webrtc_relay
from services.adapter_registry import AdapterRegistry
from services.runtime_state import state


class _FakeLocalIOS:
    platform = "ios"
    source_id = "ios"

    def is_backend_available(self):
        return True


class TestNodesApi(unittest.TestCase):
    def setUp(self):
        self._prev = dict(state.devices)
        state.devices.clear()

    def tearDown(self):
        state.devices.clear()
        state.devices.update(self._prev)

    def test_exponential_backoff_and_force_reconnect_and_api_nodes(self):
        should_fail = {"flag": False}

        def handler(request: httpx.Request) -> httpx.Response:
            if should_fail["flag"]:
                raise httpx.ConnectError("node down", request=request)
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"ok": True})
            if request.url.path == "/api/devices":
                return httpx.Response(
                    200,
                    json={
                        "devices": ["AND-1", "AND-2"],
                        "names": {"AND-1": "Note 14", "AND-2": "K30 Pro"},
                        "geometry": {},
                    },
                )
            return httpx.Response(404)

        cfg = RemoteNodeConfig(id="rog", url="http://127.0.0.1:18002", type="scrcpy", username="g", password="p")
        remote = RemoteNodeAdapter({}, cfg, transport=httpx.MockTransport(handler))
        registry = AdapterRegistry({})
        registry.register(_FakeLocalIOS(), "ios")
        registry.register(remote, "node:rog")

        # 1. Initial discover succeeds
        remote.discover()
        st = remote.node_status()
        self.assertTrue(st["online"])
        self.assertEqual(st["device_count"], 2)
        self.assertIsNotNone(st["latency_ms"])
        self.assertEqual(st["consecutive_failures"], 0)

        # 2. Outage triggers backoff and clears devices
        should_fail["flag"] = True
        remote.discover()
        st_down = remote.node_status()
        self.assertFalse(st_down["online"])
        self.assertEqual(st_down["consecutive_failures"], 1)
        self.assertGreater(st_down["retry_in_sec"], 0.0)
        self.assertTrue(st_down["reconnectable"])
        self.assertIn("node down", st_down["last_error"])

        # Subsequent discover within backoff window skips network poll
        should_fail["flag"] = False
        remote.discover()
        self.assertFalse(remote.node_status()["online"])

        # 3. Flask API GET /api/nodes and POST /api/nodes/rog/reconnect
        app = Flask(__name__)
        app.register_blueprint(nodes_bp)
        with patch("api.nodes_api.get_adapter", return_value=registry):
            with app.test_client() as client:
                r = client.get("/api/nodes")
                self.assertEqual(r.status_code, 200)
                payload = r.get_json()["data"]
                self.assertIn("server_time", payload)
                nodes = payload["nodes"]
                self.assertEqual(len(nodes), 2)
                local_node = [n for n in nodes if n["id"] == "ios"][0]
                self.assertFalse(local_node["reconnectable"])
                self.assertEqual(local_node["retry_in_sec"], 0.0)
                rog_node = [n for n in nodes if n["id"] == "rog"][0]
                self.assertFalse(rog_node["online"])
                self.assertGreater(rog_node["retry_in_sec"], 0.0)

                # force reconnect bypasses backoff and restores 2 devices
                r2 = client.post("/api/nodes/rog/reconnect")
                self.assertEqual(r2.status_code, 200)
                reconn = r2.get_json()["data"]["node"]
                self.assertTrue(reconn["online"])
                self.assertEqual(reconn["device_count"], 2)
                self.assertEqual(reconn["consecutive_failures"], 0)
                self.assertEqual(reconn["retry_in_sec"], 0.0)

                # Active relayed scrcpy WebRTC session surfaces in /api/nodes streams
                fake_key = ("test-sid", "AND-1")
                with scrcpy_webrtc_relay._lock:
                    scrcpy_webrtc_relay._sessions[fake_key] = {"remote_id": "AND-1", "sio": object()}
                try:
                    r3 = client.get("/api/nodes")
                    self.assertEqual(r3.status_code, 200)
                    streams = {s["udid"]: s for s in r3.get_json()["data"]["streams"]}
                    self.assertTrue(streams["AND-1"]["streaming"])
                    self.assertEqual(streams["AND-1"]["provider"], "scrcpy-webrtc")
                    self.assertEqual(streams["AND-1"]["viewers"], 1)
                finally:
                    with scrcpy_webrtc_relay._lock:
                        scrcpy_webrtc_relay._sessions.pop(fake_key, None)

                # Unknown node -> 404
                self.assertEqual(client.post("/api/nodes/missing/reconnect").status_code, 404)
