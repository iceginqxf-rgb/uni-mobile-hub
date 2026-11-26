"""Tests for Cross-OS SyncService, normalized fanout, recursion guard, and /api/sync routes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from app import create_app
from api.sync_api import bp as sync_bp
from services.device_models import MobileDevice
from services.ios_control_service import IOSControlService, ios_control_service as control_service
from services.runtime_state import state
from services.sync_service import sync_service


class _FakeControlAdapter:
    def __init__(self, controllers: dict):
        self._controllers = controllers

    def controller(self, udid: str):
        return self._controllers[udid]


class TestSyncService(unittest.TestCase):
    def setUp(self):
        self._prev_devices = dict(state.devices)
        sync_service.clear_group()
        state.devices.clear()

        self.master = "M-ANDROID-1"
        self.slave_ios = "S-IOS-1"
        self.slave_fail = "S-ANDROID-FAIL"

        state.devices[self.master] = MobileDevice(
            udid=self.master, platform="android", source="adb",
            name="MasterPixel", screen_width=1000, screen_height=2000,
        )
        state.devices[self.slave_ios] = MobileDevice(
            udid=self.slave_ios, platform="ios", source="ios",
            name="SlaveiPhone", screen_width=400, screen_height=800,
        )
        state.devices[self.slave_fail] = MobileDevice(
            udid=self.slave_fail, platform="android", source="adb",
            name="BrokenSlave", screen_width=500, screen_height=1000,
        )

        self.c_master = MagicMock()
        self.c_ios = MagicMock()
        self.c_fail = MagicMock()
        self.c_fail.tap.side_effect = RuntimeError("slave offline")

        self.fake_adapter = _FakeControlAdapter({
            self.master: self.c_master,
            self.slave_ios: self.c_ios,
            self.slave_fail: self.c_fail,
        })

    def tearDown(self):
        sync_service.clear_group()
        state.devices.clear()
        state.devices.update(self._prev_devices)

    def test_cross_os_normalized_tap_and_swipe_and_text_fanout(self):
        with patch("services.ios_control_service.get_adapter", return_value=self.fake_adapter):
            sync_service.set_group(self.master, [self.master, self.slave_ios, self.slave_ios])
            self.assertEqual(sync_service.get_slaves(self.master), [self.slave_ios])

            # Tap at 50%, 25% on 1000x2000 master -> 200, 200 on 400x800 iOS slave
            control_service.tap(self.master, {"x": 500, "y": 500})
            self.c_master.tap.assert_called_once_with(500, 500)
            self.c_ios.tap.assert_called_once_with(200, 200)

            # Swipe 10%->90% horizontally
            control_service.swipe(self.master, {"x1": 100, "y1": 1000, "x2": 900, "y2": 1000, "duration": 0.4})
            self.c_ios.swipe.assert_called_once_with(40, 400, 360, 400, 0.4)

            # Text & key broadcast
            control_service.input_text(self.master, {"text": "hello"})
            self.c_ios.input_text.assert_called_once_with("hello")

            control_service.key(self.master, "home")
            self.c_master.press_button.assert_called_with("home")
            self.c_ios.press_button.assert_called_with("home")

    def test_no_recursion_when_slave_is_also_a_master(self):
        with patch("services.ios_control_service.get_adapter", return_value=self.fake_adapter):
            sync_service.set_group(self.master, [self.slave_ios])
            sync_service.set_group(self.slave_ios, [self.master])

            control_service.tap(self.master, {"x": 500, "y": 1000})
            self.assertEqual(self.c_master.tap.call_count, 1)
            self.assertEqual(self.c_ios.tap.call_count, 1)

    def test_failing_slave_isolated_does_not_break_healthy_slave_or_master(self):
        with patch("services.ios_control_service.get_adapter", return_value=self.fake_adapter):
            sync_service.set_group(self.master, [self.slave_fail, self.slave_ios])
            res = control_service.tap(self.master, {"x": 250, "y": 500})
            self.assertEqual(res, {"x": 250, "y": 500})
            self.c_ios.tap.assert_called_once_with(100, 200)
            self.c_fail.tap.assert_called_once()

    def test_sync_api_routes(self):
        gate_app, _ = create_app()
        with gate_app.test_client() as client:
            r = client.get("/api/sync/status")
            self.assertEqual(r.status_code, 401)

        app = Flask(__name__)
        app.register_blueprint(sync_bp)
        state.devices[self.master] = MobileDevice(
            udid=self.master, platform="android", source="adb",
            name="MasterPixel", screen_width=1000, screen_height=2000,
        )
        state.devices[self.slave_ios] = MobileDevice(
            udid=self.slave_ios, platform="ios", source="ios",
            name="SlaveiPhone", screen_width=400, screen_height=800,
        )
        with app.test_client() as client:
            r = client.get("/api/sync/status")
            self.assertEqual(r.status_code, 200)

            admin_user = {"id": 1, "username": "admin", "role": "admin", "is_active": 1}
            with patch("services.auth_service.current_user", return_value=admin_user):
                r = client.post("/api/sync/group", json={"master": self.master, "slaves": [self.slave_ios]})
                self.assertEqual(r.status_code, 200, r.get_json())
                self.assertEqual(r.get_json()["data"]["groups"], {self.master: [self.slave_ios]})

                r = client.get("/api/sync/status")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.get_json()["data"]["groups"], {self.master: [self.slave_ios]})

                r = client.delete(f"/api/sync/group/{self.master}")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.get_json()["data"]["groups"], {})
