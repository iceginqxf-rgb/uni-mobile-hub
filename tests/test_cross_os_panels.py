"""Integration tests for unified APK/IPA installation, Android buttons, and live logcat/syslog SSE."""

from __future__ import annotations

import io
import json
import subprocess

import httpx
import pytest
from flask import Flask

from android.device_models import AndroidDevice
from api.apps_api import bp as apps_bp
from api.devices_api import bp as devices_bp
from nodes.node_config import parse_remote_nodes
from nodes.remote_node_adapter import RemoteNodeAdapter
from services import adapter_registry, auth_service
from services.adapter_registry import AdapterRegistry
from services.ios_control_service import IOSControlService
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


def test_apps_api_accepts_apk_upload_for_android(monkeypatch):
    installed: list[tuple[str, str]] = []

    class _StubAndroidAdapter:
        source_id = "android"
        platform = "android"

        def list_apps(self, udid, system=False):
            return {"apps": [{"bundle_id": "com.demo.app", "name": "Demo"}]}

        def install_app(self, udid, path):
            installed.append((udid, path))
            return {"installed": True, "detail": "Success"}

        def uninstall_app(self, udid, bundle_id):
            return {"bundle_id": bundle_id, "uninstalled": True}

    reg = AdapterRegistry({})
    reg.register(_StubAndroidAdapter(), "android")
    state.upsert_device(AndroidDevice(udid="and-apk", name="Redmi", connected=True))

    import services

    monkeypatch.setattr(services, "_registry", reg)
    monkeypatch.setattr("services.ios_app_service.get_adapter", reg.adapter_for)

    app = Flask(__name__)
    app.register_blueprint(apps_bp)
    client = app.test_client()

    resp = client.post(
        "/api/devices/and-apk/apps/install",
        data={"file": (io.BytesIO(b"PK\x03\x04fake-apk"), "sample.apk")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["installed"] is True
    assert len(installed) == 1
    assert installed[0][1].endswith(".apk")


def test_syslog_sse_streams_remote_scrcpy_logcat(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/device/win-and-1/logcat":
            assert request.url.params.get("level") == "W"
            sse = b"data: 11-27 07:30:00.000 W/ActivityManager: sample line\n\n"
            return httpx.Response(200, content=sse, headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"devices": ["win-and-1"], "names": {"win-and-1": "Redmi"}})

    node = parse_remote_nodes([{"id": "win-1", "type": "scrcpy", "url": "http://127.0.0.1:9998"}])[0]
    adapter = RemoteNodeAdapter({}, node, transport=httpx.MockTransport(handler))
    reg = AdapterRegistry({})
    reg.register(adapter, adapter.source_id)
    reg.discover()

    import services

    monkeypatch.setattr(services, "_registry", reg)
    monkeypatch.setattr("services.reservation_service.assert_owner", lambda _u, _user: None)
    monkeypatch.setattr(auth_service, "current_user", lambda: {"id": 1, "role": "admin"})

    app = Flask(__name__)
    app.register_blueprint(devices_bp)
    client = app.test_client()

    resp = client.get("/api/devices/win-and-1/syslog?level=W")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "ActivityManager: sample line" in text


def test_control_service_accepts_android_nav_buttons_and_keys():
    pressed: list[str] = []

    class _StubCtrl:
        def press_button(self, name):
            pressed.append(name)

    class _StubReg:
        def controller(self, _udid):
            return _StubCtrl()

    import services.ios_control_service as ctl_mod

    orig = ctl_mod.get_adapter
    ctl_mod.get_adapter = lambda *_a, **_kw: _StubReg()
    try:
        svc = IOSControlService()
        for btn in ("back", "recent", "rotate", "power", "wake", "sleep"):
            assert svc.button("and-1", btn) == {"button": btn}
        for k in ("back", "home", "recent"):
            assert svc.key("and-1", k) == {"key": k}
        assert pressed == ["back", "recent", "rotate", "power", "wake", "sleep", "back", "home", "recent"]
    finally:
        ctl_mod.get_adapter = orig
