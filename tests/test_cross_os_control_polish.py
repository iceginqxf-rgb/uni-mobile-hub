"""Tests for Issue #12: Unicode clipboard, Android rotation geometry, and rotate state sync."""

from __future__ import annotations

import base64
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from android.adb_client import AdbClient
from ios.ios_adapter import IOSAdapter
from ios.wda_controller import WDAController
from services.device_models import MobileDevice
from services.ios_control_service import ios_control_service
from services.runtime_state import state


class _FakeAdapter:
    def __init__(self, ctrl):
        self._ctrl = ctrl

    def controller(self, _udid):
        return self._ctrl


class TestCrossOSControlPolish(unittest.TestCase):
    def setUp(self):
        self._prev = dict(state.devices)
        state.devices.clear()

    def tearDown(self):
        state.devices.clear()
        state.devices.update(self._prev)

    def test_unicode_clipboard_uses_ascii_base64_over_ssh(self):
        adb = AdbClient(adb_bin=r"C:\adb\adb.exe", ssh_host="rog-host")
        cmds = []
        adb.shell = lambda serial, cmd, timeout=None: (cmds.append((serial, cmd)), "")[1]  # type: ignore[method-assign]

        adb.set_clipboard("DEV1", "你好，跨端剪贴板！")
        self.assertEqual(len(cmds), 1)
        sent = cmds[0][1]
        self.assertTrue(sent.isascii(), "SSH command itself must remain pure ASCII")
        expected_b64 = base64.b64encode("你好，跨端剪贴板！".encode("utf-8")).decode("ascii")
        self.assertIn(expected_b64, sent)
        self.assertIn("base64 -d", sent)

    def test_android_screen_size_swaps_on_landscape_rotation(self):
        adb = AdbClient()
        adb._meta_cache["DEV1"] = {"width": 1080, "height": 2400}

        adb.shell = lambda serial, cmd, timeout=None: "mCurrentRotation=ROTATION_90"  # type: ignore[method-assign]
        self.assertEqual(adb.get_orientation("DEV1"), "LANDSCAPE")
        self.assertEqual(adb.get_screen_size("DEV1"), (2400, 1080))

        adb.shell = lambda serial, cmd, timeout=None: "mCurrentRotation=ROTATION_0"  # type: ignore[method-assign]
        self.assertEqual(adb.get_orientation("DEV1"), "PORTRAIT")
        self.assertEqual(adb.get_screen_size("DEV1"), (1080, 2400))

    def test_rotate_button_updates_device_geometry_and_emits_event(self):
        udid = "AND-ROT-1"
        state.devices[udid] = MobileDevice(
            udid=udid, platform="android", source="adb",
            screen_width=1080, screen_height=2400, orientation="PORTRAIT",
        )
        ctrl = MagicMock()
        ctrl.get_window_size.return_value = (2400, 1080)
        ctrl.get_orientation.return_value = "LANDSCAPE"

        with (
            patch("services.ios_control_service.get_adapter", return_value=_FakeAdapter(ctrl)),
            patch("services.event_bus.emit") as emit_mock,
        ):
            res = ios_control_service.button(udid, "rotate")
            self.assertEqual(res, {"button": "rotate"})
            ctrl.press_button.assert_called_once_with("rotate")
            dev = state.get_device(udid)
            self.assertEqual((dev.screen_width, dev.screen_height), (2400, 1080))
            self.assertEqual(dev.orientation, "LANDSCAPE")
            emit_mock.assert_called_with("devices:changed", {"reason": "rotated", "udid": udid})

    def test_ios_adapter_connect_serializes_per_udid(self):
        adapter = IOSAdapter({})
        active = {"n": 0, "max": 0}

        def fake_connect(udid: str):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            time.sleep(0.05)
            active["n"] -= 1
            return udid

        adapter._connect_unlocked = fake_connect  # type: ignore[method-assign]
        t1 = threading.Thread(target=adapter.connect, args=("IOS-SERIAL-1",))
        t2 = threading.Thread(target=adapter.connect, args=("IOS-SERIAL-1",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(active["max"], 1)

    def test_wda_swipe_hold_end_adds_pause_before_pointer_up(self):
        ctrl = WDAController("http://127.0.0.1:18999")
        sent = []
        ctrl._session_request = lambda method, sub, **kw: sent.append((method, sub, kw["json"]))  # type: ignore[method-assign]
        ctrl.swipe(200, 900, 200, 500, duration=0.35, hold_end=0.55)
        actions = sent[0][2]["actions"][0]["actions"]
        self.assertEqual([a["type"] for a in actions], ["pointerMove", "pointerDown", "pointerMove", "pause", "pointerUp"])
        self.assertEqual(actions[3]["duration"], 550)

        # Controllers without hold_end stay backwards-compatible via IOSControlService
        udid = "AND-SIMPLE-1"
        state.devices[udid] = MobileDevice(udid=udid, platform="android", source="adb", screen_width=1080, screen_height=2400)
        calls = []

        class _SimpleCtrl:
            def swipe(self, x1, y1, x2, y2, duration=0.3):
                calls.append((x1, y1, x2, y2, duration))

        with patch("services.ios_control_service.get_adapter", return_value=_FakeAdapter(_SimpleCtrl())):
            ios_control_service.swipe(udid, {"x1": 10, "y1": 900, "x2": 10, "y2": 400, "duration": 0.35, "hold_end": 0.5})
        self.assertEqual(calls, [(10, 900, 10, 400, 0.35)])

    def test_wda_press_button_recent_triggers_app_switcher(self):
        ctrl = WDAController("http://127.0.0.1:18999")
        ctrl.get_window_size = lambda: (428, 926)  # type: ignore[method-assign]
        calls = []
        ctrl._session_request = lambda method, sub, **kw: calls.append((method, sub, kw["json"]))  # type: ignore[method-assign]

        ctrl.press_button("recent")
        self.assertEqual(calls[0][1], "/actions")
        seq = calls[0][2]["actions"][0]["actions"]
        self.assertEqual([a["type"] for a in seq], ["pointerMove", "pointerDown", "pointerMove", "pause", "pointerUp"])
        self.assertEqual((seq[0]["x"], seq[0]["y"]), (214, 924))
        self.assertEqual(seq[3]["duration"], 900)

    def test_health_disables_hevc_unless_explicitly_enabled(self):
        from flask import Flask
        from api.health_api import bp as health_bp

        class _StubAdapter:
            def __init__(self, cfg):
                self.config = cfg
                self.webrtc = None

            def is_backend_available(self):
                return True

        app = Flask(__name__)
        app.register_blueprint(health_bp)
        with (
            patch("api.health_api.get_adapter", return_value=_StubAdapter({"IOS_ENABLE_HEVC": "0"})),
            patch("api.health_api._hevc_available", return_value=True),
        ):
            with app.test_client() as client:
                r = client.get("/api/health")
                self.assertEqual(r.status_code, 200)
                self.assertFalse(r.get_json()["data"]["hevc_available"])

        with (
            patch("api.health_api.get_adapter", return_value=_StubAdapter({"IOS_ENABLE_HEVC": "1"})),
            patch("api.health_api._hevc_available", return_value=True),
        ):
            with app.test_client() as client:
                r = client.get("/api/health")
                self.assertTrue(r.get_json()["data"]["hevc_available"])

    def test_reservation_release_emits_devices_changed(self):
        from services import reservation_service as reservations

        emitted = []
        with (
            patch.object(reservations, "get_conn") as mock_conn,
            patch.object(reservations, "_teardown"),
            patch("services.reservation_service.events.emit", side_effect=lambda ev, p: emitted.append((ev, p))),
        ):
            mock_conn.return_value.execute.return_value.rowcount = 1
            self.assertTrue(reservations.release("DEV-1", reason="released"))
        event_names = [e[0] for e in emitted]
        self.assertIn("device_released", event_names)
        self.assertIn("devices:changed", event_names)

    def test_webrtc_bridge_rtc_configuration_defaults_to_no_stun(self):
        from services.webrtc_bridge import WebRTCBridge

        bridge = WebRTCBridge({})
        cfg = bridge._rtc_configuration()
        self.assertEqual(cfg.iceServers, [])

        bridge_custom = WebRTCBridge(
            {"IOS_WEBRTC_ICE_SERVERS": "stun:a.example:3478, stun:b.example:3478"}
        )
        cfg_custom = bridge_custom._rtc_configuration()
        self.assertEqual(len(cfg_custom.iceServers), 2)
        self.assertEqual(cfg_custom.iceServers[0].urls, "stun:a.example:3478")
        self.assertEqual(cfg_custom.iceServers[1].urls, "stun:b.example:3478")

    def test_ios_adapter_caches_ddi_and_wda_bundle(self):
        adapter = IOSAdapter({"IOS_USE_GOIOS": "1", "IOS_GOIOS_TUNNEL": "0"})
        adapter.goios = MagicMock()
        adapter.goios.is_available.return_value = True
        adapter.goios.list_apps.return_value = [{"bundle_id": "com.example.WDA.xctrunner"}]
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        adapter.goios.run_wda.return_value = fake_proc
        adapter._mount_ddi = MagicMock(return_value=(True, "ok"))  # type: ignore[method-assign]
        adapter._poll_wda = MagicMock()  # type: ignore[method-assign]

        ctrl = MagicMock()
        ctrl.health_check.return_value = True
        adapter._bring_up_wda("IOS-CACHE-1", ctrl)
        # Simulate runner exited on second connect while DDI & bundle stay cached
        fake_proc.poll.return_value = 1
        adapter._bring_up_wda("IOS-CACHE-1", ctrl)

        adapter._mount_ddi.assert_called_once_with("IOS-CACHE-1")
        adapter.goios.list_apps.assert_called_once_with("IOS-CACHE-1")

        # Cache clears when health_check fails after _bring_up_wda
        state.devices["IOS-CACHE-1"] = MobileDevice(udid="IOS-CACHE-1", platform="ios", source="ios")
        adapter._wda_bundle_cache["IOS-CACHE-1"] = "com.example.WDA.xctrunner"
        adapter._ddi_mounted.add("IOS-CACHE-1")
        adapter.port_forward = MagicMock()
        adapter.port_forward.start_forward.return_value = MagicMock(local_port=18100)
        ctrl_bad = MagicMock()
        ctrl_bad.health_check.return_value = False
        adapter._controller = MagicMock(return_value=ctrl_bad)  # type: ignore[method-assign]
        adapter._bring_up_wda = MagicMock()  # type: ignore[method-assign]
        from utils.app_errors import AppError

        with self.assertRaises(AppError):
            adapter._connect_unlocked("IOS-CACHE-1")
        self.assertNotIn("IOS-CACHE-1", adapter._ddi_mounted)
        self.assertNotIn("IOS-CACHE-1", adapter._wda_bundle_cache)
