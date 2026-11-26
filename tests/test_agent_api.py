"""Tests for Agent Bearer Token auth and unified /api/v1/agent/* endpoints."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.agent_api import bp as agent_bp
from app import create_app
from services.device_models import MobileDevice
from services.ios_control_service import ios_control_service
from services.runtime_state import state


class _FakeAdapter:
    platform = "multi"

    def __init__(self, controllers: dict):
        self._controllers = controllers
        self.connect_calls = []

    def discover(self):
        return list(state.devices.values())

    def adapter_for(self, udid: str):
        return self

    def controller(self, udid: str):
        return self._controllers[udid]

    def connect(self, udid: str):
        self.connect_calls.append(udid)
        dev = state.get_device(udid)
        if dev:
            dev.connected = True
        return dev

    def list_apps(self, udid: str, system: bool = False):
        return {"apps": [{"bundle_id": "com.example.demo", "name": "Demo"}], "system": system}


class TestAgentApi(unittest.TestCase):
    def setUp(self):
        self._prev_devices = dict(state.devices)
        state.devices.clear()
        self.and_udid = "AND-PIXEL-1"
        self.ios_udid = "IOS-PHONE-1"

        state.devices[self.and_udid] = MobileDevice(
            udid=self.and_udid, platform="android", source="adb",
            name="Pixel", screen_width=1000, screen_height=2000, connected=False,
        )
        state.devices[self.ios_udid] = MobileDevice(
            udid=self.ios_udid, platform="ios", source="ios",
            name="iPhone", screen_width=390, screen_height=844, connected=True,
        )

        # Tiny valid 1x1 PNG so PIL/to_jpeg works if needed, or mock screenshot bytes
        self.c_and = MagicMock()
        self.c_ios = MagicMock()
        self.c_and.screenshot.return_value = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
        )
        self.fake = _FakeAdapter({self.and_udid: self.c_and, self.ios_udid: self.c_ios})

    def tearDown(self):
        state.devices.clear()
        state.devices.update(self._prev_devices)

    def test_bearer_token_auth_gate(self):
        app, _ = create_app()
        app.config["AGENT_API_TOKEN"] = "secret-agent-tok"
        state.devices[self.and_udid] = MobileDevice(
            udid=self.and_udid, platform="android", source="adb",
            name="Pixel", screen_width=1000, screen_height=2000, connected=True,
        )

        with patch("api.agent_api.get_adapter", return_value=self.fake):
            with app.test_client() as client:
                # Missing auth -> 401
                self.assertEqual(client.get("/api/v1/agent/devices").status_code, 401)
                # Wrong token -> 401
                self.assertEqual(
                    client.get("/api/v1/agent/devices", headers={"Authorization": "Bearer wrong"}).status_code,
                    401,
                )
                # Valid Bearer -> 200
                r = client.get("/api/v1/agent/devices", headers={"Authorization": "Bearer secret-agent-tok"})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.get_json()["data"]["devices"][0]["udid"], self.and_udid)
                # Valid X-Agent-Token -> 200
                r2 = client.get("/api/v1/agent/devices", headers={"X-Agent-Token": "secret-agent-tok"})
                self.assertEqual(r2.status_code, 200)
                self.assertIn("devices", r2.get_json()["data"])

                # Empty token disables static token auth
                app.config["AGENT_API_TOKEN"] = ""
                self.assertEqual(
                    client.get("/api/v1/agent/devices", headers={"Authorization": "Bearer secret-agent-tok"}).status_code,
                    401,
                )

    def test_agent_endpoints_auto_connect_screenshot_normalized_coords_and_apps(self):
        app = Flask(__name__)
        app.register_blueprint(agent_bp)
        token_user = {"id": 0, "username": "agent-api", "role": "admin", "is_active": 1}

        with (
            patch("services.auth_service.current_user", return_value=token_user),
            patch("api.agent_api.get_adapter", return_value=self.fake),
            patch("services.ios_app_service.get_adapter", return_value=self.fake),
            patch("services.ios_control_service.get_adapter", return_value=self.fake),
        ):
            with app.test_client() as client:
                # Auto-connect triggers on first tap against disconnected Android device
                r = client.post(f"/api/v1/agent/devices/{self.and_udid}/tap", json={"nx": 0.5, "ny": 0.25})
                self.assertEqual(r.status_code, 200, r.get_json())
                self.assertIn(self.and_udid, self.fake.connect_calls)
                self.c_and.tap.assert_called_once_with(500, 500)

                # Normalized swipe + longpress
                r = client.post(
                    f"/api/v1/agent/devices/{self.ios_udid}/swipe",
                    json={"nx1": 0.5, "ny1": 0.8, "nx2": 0.5, "ny2": 0.2, "duration": 0.4},
                )
                self.assertEqual(r.status_code, 200)
                self.c_ios.swipe.assert_called_once_with(195, 675, 195, 169, 0.4)

                r = client.post(
                    f"/api/v1/agent/devices/{self.ios_udid}/longpress",
                    json={"nx": 0.5, "ny": 0.5, "duration": 1.0},
                )
                self.assertEqual(r.status_code, 200)
                self.c_ios.long_press.assert_called_once_with(195, 422, 1.0)

                # Raw JPEG screenshot
                r = client.get(f"/api/v1/agent/devices/{self.and_udid}/screenshot")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.mimetype, "image/jpeg")
                self.assertEqual(r.data[:2], b"\xff\xd8")
                self.assertEqual(r.headers.get("X-Device-Width"), "1000")

                # JSON screenshot
                r = client.get(f"/api/v1/agent/devices/{self.and_udid}/screenshot?format=json")
                self.assertEqual(r.status_code, 200)
                self.assertIn("data:image/jpeg;base64,", r.get_json()["data"]["image"])

                # Text + enter
                r = client.post(f"/api/v1/agent/devices/{self.and_udid}/text", json={"text": "hi", "enter": True})
                self.assertEqual(r.status_code, 200)
                self.c_and.input_text.assert_any_call("hi")
                self.c_and.input_text.assert_any_call("\n")

                # Key / button dispatch
                r = client.post(f"/api/v1/agent/devices/{self.and_udid}/key", json={"name": "home"})
                self.assertEqual(r.status_code, 200)
                self.c_and.home.assert_called_once()

                # Apps + open/close app
                r = client.get(f"/api/v1/agent/devices/{self.and_udid}/apps")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.get_json()["data"]["apps"][0]["bundle_id"], "com.example.demo")

                r = client.post(f"/api/v1/agent/devices/{self.and_udid}/open_app", json={"app": "com.example.demo"})
                self.assertEqual(r.status_code, 200)
                self.c_and.launch_app.assert_called_once_with("com.example.demo")

                r = client.post(f"/api/v1/agent/devices/{self.and_udid}/close_app", json={"app": "com.example.demo"})
                self.assertEqual(r.status_code, 200)
                self.c_and.terminate_app.assert_called_once_with("com.example.demo")
