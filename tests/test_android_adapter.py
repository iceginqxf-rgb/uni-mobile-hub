"""Unit tests for local AndroidAdapter, AdbClient, AndroidController, and service routing."""

from __future__ import annotations

import io
import os
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from android.adb_client import AdbClient
from android.android_adapter import AndroidAdapter
from services import get_adapter, init_platform
from services.device_info import collect as collect_device_info
from services.ios_app_service import IOSAppService
from services.ios_control_service import IOSControlService
from services.ios_file_service import IOSFileService
from services.runtime_state import state
from utils.app_errors import AppError


@pytest.fixture(autouse=True)
def _clean_state():
    state.devices.clear()
    state.controllers.clear()
    state.streams.clear()
    state.viewers.clear()
    state.last_activity.clear()
    yield
    state.devices.clear()
    state.controllers.clear()
    state.streams.clear()
    state.viewers.clear()
    state.last_activity.clear()


def _fake_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 240), (10, 80, 200)).save(buf, format="PNG")
    return buf.getvalue()


def test_android_adapter_discover_connect_control_and_services(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    png_bytes = _fake_png()

    def fake_run(cmd, capture_output=True, text=True, timeout=15):
        adb_args = cmd[1:]
        calls.append(adb_args)
        joined = " ".join(adb_args)
        if adb_args == ["devices", "-l"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                "List of devices attached\nand-001 device usb:1-1 product:lmi model:Redmi_K30_Pro transport_id:6\n",
                "",
            )
        if "getprop ro.product.marketname" in joined:
            return subprocess.CompletedProcess(
                cmd,
                0,
                "Redmi K30 Pro\n---\n\n---\nRedmi K30 Pro\n---\n16\n---\nPhysical size: 1080x2400\n---\ncom.bytedance.android.doubaoime/.ImeService\n",
                "",
            )
        if "dumpsys input" in joined:
            return subprocess.CompletedProcess(cmd, 0, "SurfaceOrientation: 0\n", "")
        if "exec-out" in joined and "screencap" in joined:
            return subprocess.CompletedProcess(cmd, 0, png_bytes, "")
        if "pm list packages" in joined:
            return subprocess.CompletedProcess(cmd, 0, "package:com.tencent.mm\npackage:com.example.demo\n", "")
        if "install" in adb_args:
            return subprocess.CompletedProcess(cmd, 0, "Success\n", "")
        if "uninstall" in adb_args:
            return subprocess.CompletedProcess(cmd, 0, "Success\n", "")
        if "ls" in joined or "[ -d" in joined:
            return subprocess.CompletedProcess(cmd, 0, "D|/sdcard/Download\nF|/sdcard/notes.txt\n", "")
        if "pull" in adb_args:
            dst_local = adb_args[-1]
            with open(dst_local, "wb") as fh:
                fh.write(b"hello-android")
            return subprocess.CompletedProcess(cmd, 0, "1 file pulled", "")
        if "push" in adb_args:
            return subprocess.CompletedProcess(cmd, 0, "1 file pushed", "")
        if "dumpsys battery" in joined:
            return subprocess.CompletedProcess(cmd, 0, "Qualcomm\n---\narm64-v8a\n---\n16.0\n---\nlevel: 85\nstatus: 2\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("android.adb_client.shutil.which", lambda name: "/usr/local/bin/adb" if name == "adb" else None)
    monkeypatch.setattr("android.adb_client.subprocess.run", fake_run)

    reg = init_platform({"IOS_ENABLED": "0", "ANDROID_ENABLED": "1"})
    devices = reg.discover()
    assert len(devices) == 1
    dev = devices[0]
    assert dev.udid == "and-001"
    assert dev.platform == "android"
    assert dev.name == "Redmi K30 Pro"
    assert dev.screen_width == 1080
    assert dev.screen_height == 2400

    connected = reg.connect("and-001")
    assert connected.connected is True

    svc = IOSControlService()
    res = svc.tap("and-001", {"x": 54, "y": 120, "display_width": 108, "display_height": 240})
    assert res == {"x": 540, "y": 1200}
    svc.button("and-001", "back")
    svc.key("and-001", "recent")
    # Unicode without ADBKeyBoard falls back to clipboard + paste keyevent 279.
    svc.input_text("and-001", {"text": "你好世界"})
    assert any("cmd clipboard set-text" in " ".join(c) for c in calls)
    assert any("input keyevent 279" in " ".join(c) for c in calls)

    shot = svc.screenshot("and-001", as_base64=False)
    assert shot["bytes"][:2] == b"\xff\xd8"

    apps = IOSAppService.list_apps("and-001")
    assert [a["bundle_id"] for a in apps["apps"]] == ["com.example.demo", "com.tencent.mm"]
    assert IOSAppService.install("and-001", "/tmp/demo.apk")["installed"] is True
    assert IOSAppService.uninstall("and-001", "com.example.demo")["uninstalled"] is True

    tree = IOSFileService.tree("and-001", ".")
    assert tree["entries"][0]["isDir"] is True
    pulled = IOSFileService.pull_to_temp("and-001", "/sdcard/notes.txt")
    assert open(pulled, "rb").read() == b"hello-android"
    os.remove(pulled)

    info = collect_device_info("and-001")
    assert info["platform"] == "android"
    assert info["battery"] == {"level": 85, "charging": True}

    reg.disconnect("and-001")
    assert state.get_device("and-001").connected is False


def test_android_adapter_degrades_when_adb_missing(monkeypatch):
    monkeypatch.setattr("android.adb_client.shutil.which", lambda _name: None)
    adapter = AndroidAdapter({"ANDROID_ADB_BIN": ""})
    assert adapter.is_backend_available() is False
    assert adapter.discover() == []
    with pytest.raises(AppError):
        adapter.adb.shell("x", "echo hi")
