"""Tests for iOS 17+ DVT memory metrics, running-apps filtering, and HTTP route."""

from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from api.apps_api import bp as apps_bp
from ios.dvt_metrics import filter_running_apps, parse_sysmon_memory
from services.device_info import collect as collect_device_info
from services.device_models import MobileDevice
from services.runtime_state import state


class TestIosDvtMetrics(unittest.TestCase):
    def setUp(self):
        self._prev = dict(state.devices)
        state.devices.clear()

    def tearDown(self):
        state.devices.clear()
        state.devices.update(self._prev)

    def test_parse_sysmon_memory_pages_to_bytes(self):
        attrs = [
            "physMemSize",
            "vmIntPageCount",
            "vmPurgeableCount",
            "vmWireCount",
            "vmCompressorPageCount",
        ]
        vals = [364132, 93654, 3756, 62726, 82098]
        res = parse_sysmon_memory(attrs, vals)
        expected_total = 364132 * 16384
        expected_used = ((93654 - 3756) + 62726 + 82098) * 16384
        self.assertEqual(res, {"used": expected_used, "total": expected_total})

    def test_parse_sysmon_memory_bytes_and_fallbacks(self):
        # Already in bytes (> 1e9)
        res_bytes = parse_sysmon_memory(
            ["physMemSize", "vmUsedCount"],
            [6_000_000_000, 3_200_000_000],
        )
        self.assertEqual(res_bytes, {"used": 3_200_000_000, "total": 6_000_000_000})

        # vmActiveCount fallback (clamped to total)
        res_active = parse_sysmon_memory(
            ["physMemSize", "vmActiveCount", "vmWireCount", "vmCompressorPageCount"],
            [1000, 800, 300, 100],
        )
        self.assertEqual(res_active, {"used": 1000 * 16384, "total": 1000 * 16384})

        # Missing / invalid physMemSize returns None
        self.assertIsNone(parse_sysmon_memory(["vmUsedCount"], [123]))
        self.assertIsNone(parse_sysmon_memory(["physMemSize", "vmUsedCount"], [0, 123]))
        self.assertIsNone(parse_sysmon_memory(["physMemSize", "vmUsedCount"], [True, 123]))

    def test_filter_running_apps_excludes_wda_and_hidden_and_sorts(self):
        t_old = datetime.datetime(2026, 11, 26, 10, 0, 0, tzinfo=datetime.timezone.utc)
        t_mid = datetime.datetime(2026, 11, 26, 11, 0, 0, tzinfo=datetime.timezone.utc)
        t_new = datetime.datetime(2026, 11, 26, 12, 0, 0, tzinfo=datetime.timezone.utc)
        procs = [
            {"isApplication": False, "bundleIdentifier": "com.apple.notifyd", "name": "notifyd", "pid": 10},
            {"isApplication": True, "bundleIdentifier": "com.facebook.WebDriverAgentRunner.xctrunner", "name": "WebDriverAgentRunner-Runner", "pid": 500, "realAppName": "/var/containers/Bundle/Application/X/WDA.app/WDA"},
            {"isApplication": True, "bundleIdentifier": "com.apple.SpringBoard", "name": "SpringBoard", "pid": 60, "realAppName": "/System/Library/CoreServices/SpringBoard.app/SpringBoard"},
            {"isApplication": True, "bundleIdentifier": "com.apple.ScreenshotServicesService", "name": "ScreenshotServicesService", "pid": 300, "realAppName": "/Applications/ScreenshotServicesService.app/ScreenshotServicesService"},
            {"isApplication": True, "bundleIdentifier": "com.apple.EscrowSecurityAlert", "name": "EscrowSecurityAlert", "pid": 301, "realAppName": "/System/Library/CoreServices/EscrowSecurityAlert.app/EscrowSecurityAlert"},
            {"isApplication": True, "bundleIdentifier": "com.example.chat", "displayLocalizedAppName": "Chat", "name": "Chat", "pid": 100, "realAppName": "/var/containers/Bundle/Application/1/Chat.app/Chat", "startDate": t_old},
            # Duplicate bundle_id with higher PID should win
            {"isApplication": True, "bundleIdentifier": "com.example.chat", "displayLocalizedAppName": "Chat", "name": "Chat", "pid": 150, "realAppName": "/var/containers/Bundle/Application/1/Chat.app/Chat", "startDate": t_mid},
            {"isApplication": True, "bundleIdentifier": "com.apple.mobilesafari", "displayLocalizedAppName": "Safari", "name": "MobileSafari", "pid": 200, "realAppName": "/Applications/MobileSafari.app/MobileSafari", "startDate": t_new},
            {"isApplication": True, "bundleIdentifier": "com.example.fg", "displayLocalizedAppName": "NotesApp", "name": "NotesApp", "pid": 250, "realAppName": "/var/containers/Bundle/Application/2/NotesApp.app/NotesApp", "startDate": t_old},
        ]

        filtered = filter_running_apps(procs, foreground_bundle_id="com.example.fg", include_system=False)
        self.assertEqual(
            [a["bundle_id"] for a in filtered],
            ["com.example.fg", "com.example.chat", "com.apple.mobilesafari"],
        )
        self.assertTrue(filtered[0]["foreground"])
        self.assertEqual(filtered[1]["pid"], 150)

        with_sys = filter_running_apps(procs, foreground_bundle_id="", include_system=True)
        bids_sys = {a["bundle_id"] for a in with_sys}
        self.assertIn("com.apple.ScreenshotServicesService", bids_sys)
        self.assertIn("com.apple.EscrowSecurityAlert", bids_sys)
        self.assertNotIn("com.facebook.WebDriverAgentRunner.xctrunner", bids_sys)
        self.assertNotIn("com.apple.SpringBoard", bids_sys)

    def test_device_info_collect_attaches_and_handles_missing_memory(self):
        udid = "IOS-TEST-MEM-001"
        state.devices[udid] = MobileDevice(udid=udid, platform="ios", source="ios", product_type="iPhone13,4")
        mock_vals = {"DeviceName": "Test iPhone", "ProductType": "iPhone13,4", "ProductVersion": "27.2"}

        with (
            patch("services.device_info._gather", return_value=(mock_vals, {}, {})),
            patch("ios.dvt_metrics.collect_memory_info", return_value={"used": 3_000_000_000, "total": 6_000_000_000}),
        ):
            info = collect_device_info(udid)
            self.assertEqual(info["memory"], {"used": 3_000_000_000, "total": 6_000_000_000})

        with (
            patch("services.device_info._gather", return_value=(mock_vals, {}, {})),
            patch("ios.dvt_metrics.collect_memory_info", side_effect=RuntimeError("boom")),
        ):
            info2 = collect_device_info(udid)
            self.assertNotIn("memory", info2)

    def test_running_apps_http_endpoint(self):
        app = Flask(__name__)
        app.register_blueprint(apps_bp)

        ctrl = MagicMock()
        ctrl.active_app_info.return_value = {"bundleId": "com.example.fg"}
        adapter = MagicMock()
        adapter.platform = "ios"
        adapter.controller.return_value = ctrl

        expected_apps = [
            {"bundle_id": "com.example.fg", "name": "FG", "pid": 11, "foreground": True, "is_user_app": True, "start_date": ""},
        ]
        with (
            patch("services.ios_app_service.get_adapter", return_value=adapter),
            patch("ios.dvt_metrics.list_running_apps", return_value=expected_apps) as mock_list,
        ):
            with app.test_client() as client:
                r = client.get("/api/devices/IOS-TEST-01/running-apps")
                self.assertEqual(r.status_code, 200)
                data = r.get_json()["data"]
                self.assertEqual(data["foreground_bundle_id"], "com.example.fg")
                self.assertEqual(data["apps"], expected_apps)
                mock_list.assert_called_once_with(
                    "IOS-TEST-01",
                    foreground_bundle_id="com.example.fg",
                    include_system=False,
                )
