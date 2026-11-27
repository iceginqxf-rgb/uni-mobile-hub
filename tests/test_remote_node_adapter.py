"""Unit tests for Hub+Worker RemoteNodeAdapter (uni and scrcpy worker dialects)."""

from __future__ import annotations

import base64
import io
import json
import os

import httpx
import pytest
from PIL import Image

from android.device_models import AndroidDevice
from ios.device_models import IOSDevice
from nodes.node_config import parse_remote_nodes
from nodes.remote_node_adapter import RemoteNodeAdapter
from services.adapter_registry import AdapterRegistry
from services.ios_app_service import IOSAppService
from services.ios_control_service import IOSControlService
from services.ios_file_service import IOSFileService
from services.runtime_state import state


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


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 120), (30, 140, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def test_parse_remote_nodes():
    nodes = parse_remote_nodes(
        json.dumps(
            [
                {"id": "win-1", "type": "scrcpy", "url": "http://10.0.0.2:8011/", "username": "admin", "password": "pw"},
                {"id": "mac-2", "type": "uni", "url": "http://10.0.0.3:5001", "token": "tok"},
                {"id": "win-1", "url": "http://duplicate"},
            ]
        )
    )
    assert [n.id for n in nodes] == ["win-1", "mac-2"]
    assert nodes[0].url == "http://10.0.0.2:8011"
    assert nodes[1].type == "uni"
    assert parse_remote_nodes("not-json") == []


def test_remote_scrcpy_node_discovery_relogin_control_apps_files():
    jpeg = _jpeg_bytes()
    authed = {"ok": False}
    seen_calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_calls.append((request.method, request.url.path))
        if request.url.path == "/api/auth/login":
            authed["ok"] = True
            return httpx.Response(200, json={"status": "ok"})
        if not authed["ok"]:
            return httpx.Response(401, json={"error": "login required"})
        if request.url.path == "/api/devices":
            return httpx.Response(
                200,
                json={
                    "devices": ["win-and-1"],
                    "names": {"win-and-1": "Redmi Note"},
                    "geometry": {"win-and-1": {"width": 1080, "height": 2400}},
                },
            )
        if request.url.path == "/api/reservations" and request.method == "POST":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path in ("/api/start", "/api/stop"):
            return httpx.Response(200, json={"status": "started"})
        if request.url.path == "/api/snapshot":
            return httpx.Response(200, content=jpeg, headers={"Content-Type": "image/jpeg"})
        if request.url.path == "/api/device/win-and-1/keyevent":
            body = json.loads(request.content.decode())
            assert body["code"] == 4  # back
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/device/win-and-1/apps":
            return httpx.Response(200, json={"status": "ok", "packages": ["com.example.app"]})
        if request.url.path == "/api/device/win-and-1/files":
            return httpx.Response(200, json={"status": "ok", "entries": [{"name": "Download", "path": "/sdcard/Download", "isDir": True}]})
        if request.url.path == "/api/device/win-and-1/files/pull":
            return httpx.Response(200, content=b"file-body")
        if request.url.path == "/api/device/win-and-1/info":
            return httpx.Response(200, json={"status": "ok", "info": {"model": "Redmi"}})
        return httpx.Response(404, json={"error": "not found"})

    node = parse_remote_nodes([{"id": "win-node", "type": "scrcpy", "url": "http://127.0.0.1:9999", "password": "secret"}])[0]
    adapter = RemoteNodeAdapter({}, node, transport=httpx.MockTransport(handler))

    reg = AdapterRegistry({})
    reg.register(adapter, adapter.source_id)
    # Also ensure services.get_adapter resolves through our registry during app/file tests
    import services

    services._registry = reg  # noqa: SLF001

    devs = reg.discover()
    assert len(devs) == 1
    assert devs[0].node_id == "win-node"
    assert devs[0].source == "node:win-node"
    assert devs[0].stream_endpoint["mode"] == "remote_scrcpy"
    assert authed["ok"] is True

    reg.connect("win-and-1")
    assert state.get_device("win-and-1").connected is True

    IOSControlService().button("win-and-1", "back")
    shot = IOSControlService().screenshot("win-and-1", as_base64=False)
    assert shot["bytes"][:2] == b"\xff\xd8"

    apps = IOSAppService.list_apps("win-and-1")
    assert apps["apps"][0]["bundle_id"] == "com.example.app"

    tree = IOSFileService.tree("win-and-1", ".")
    assert tree["entries"][0]["path"] == "/sdcard/Download"
    local = IOSFileService.pull_to_temp("win-and-1", "/sdcard/demo.txt")
    assert open(local, "rb").read() == b"file-body"
    os.remove(local)

    info = reg.collect_device_info("win-and-1")
    assert info["node_id"] == "win-node"

    reg.disconnect("win-and-1")
    assert state.get_device("win-and-1").connected is False


def test_remote_uni_node_and_offline_isolation():
    jpeg_b64 = base64.b64encode(_jpeg_bytes()).decode("ascii")
    taps: list[dict] = []

    def uni_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer tok-123"
        if request.url.path == "/api/devices":
            return httpx.Response(
                200,
                json={"success": True, "data": {"devices": [{"udid": "u-1", "platform": "android", "name": "WorkerPhone", "screen_width": 1080, "screen_height": 2400}]}},
            )
        if request.url.path == "/api/devices/u-1/tap":
            taps.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"success": True, "data": {"x": 500, "y": 900}})
        if request.url.path == "/api/devices/u-1/screenshot":
            return httpx.Response(200, json={"success": True, "data": {"image": f"data:image/jpeg;base64,{jpeg_b64}"}})
        return httpx.Response(200, json={"success": True, "data": {}})

    def down_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("node unreachable")

    uni_node = parse_remote_nodes([{"id": "worker-a", "type": "uni", "url": "http://127.0.0.1:8881", "token": "tok-123"}])[0]
    down_node = parse_remote_nodes([{"id": "worker-b", "type": "scrcpy", "url": "http://127.0.0.1:8882"}])[0]

    # Seed a local iOS device to verify an offline remote node does not drop local devices
    state.upsert_device(IOSDevice(udid="local-ios", name="iPhone", source="ios"))
    # Seed a stale device from worker-b to verify it gets cleaned when worker-b goes offline
    state.upsert_device(AndroidDevice(udid="stale-b", name="OldPhone", source="node:worker-b", node_id="worker-b"))

    ad_a = RemoteNodeAdapter({}, uni_node, transport=httpx.MockTransport(uni_handler))
    ad_b = RemoteNodeAdapter({}, down_node, transport=httpx.MockTransport(down_handler))

    ad_a.discover()
    ad_b.discover()  # must not raise

    assert state.get_device("local-ios") is not None
    assert state.get_device("stale-b") is None
    assert state.get_device("u-1") is not None

    ad_a.controller("u-1").tap(500, 900)
    assert taps == [{"x": 500, "y": 900}]
    provider = ad_a.make_screen_provider("u-1")
    provider.start()
    assert provider.read_frame() == _jpeg_bytes()
    provider.stop()


def test_normalize_android_info_maps_metrics_and_specs():
    from nodes.remote_node_adapter import _normalize_android_info

    out = _normalize_android_info(
        {
            "abi": "arm64-v8a",
            "android_version": "16",
            "battery_level": 88,
            "battery_status": "Charging",
            "battery_temp_c": 29.4,
            "brand": "Redmi",
            "build_id": "BP2A.1",
            "connection_type": "usb",
            "density_dpi": 450,
            "ip_address": "192.168.1.50",
            "manufacturer": "Xiaomi",
            "memory_total_bytes": 8000000000,
            "memory_used_bytes": 4000000000,
            "model": "Redmi K30 Pro",
            "resolution_width": 1080,
            "resolution_height": 2400,
            "sdk": 36,
            "soc_manufacturer": "Qualcomm",
            "soc_model": "SM8250",
            "storage_total_bytes": 128000000000,
            "storage_used_bytes": 64000000000,
            "wifi_ssid": "Office-5G",
        },
        udid="SER-123",
        node_id="win-scrcpy",
    )
    assert out["marketing"] == "Redmi K30 Pro"
    assert out["os_version"] == "16"
    assert out["cpu_arch"] == "API 36 · arm64-v8a"
    assert out["resolution"] == {"w": 1080, "h": 2400}
    assert out["battery"] == {"level": 88, "charging": True, "temp_c": 29.4}
    assert out["storage"] == {"total": 128000000000, "used": 64000000000}
    assert out["memory"] == {"total": 8000000000, "used": 4000000000}
    assert out["soc"] == "Qualcomm SM8250"
    assert out["ip_address"] == "192.168.1.50"
    assert out["wifi_ssid"] == "Office-5G"
    assert out["node_id"] == "win-scrcpy"
