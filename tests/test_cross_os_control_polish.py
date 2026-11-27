"""Tests for Issue #12: Unicode clipboard, Android rotation geometry, and rotate state sync."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, patch

from android.adb_client import AdbClient
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
