"""Unit tests for MobileDevice, scoped RuntimeState.remove_missing, and AdapterRegistry."""

from __future__ import annotations

import pytest

from ios.device_models import IOSDevice
from services import get_adapter, init_platform
from services.adapter_registry import AdapterRegistry
from services.device_models import MobileDevice
from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode


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


class _FakeWebRTC:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.offers: list[str] = []
        self.stopped_sids: list[str] = []
        self.stopped_devices: list[str] = []

    def handle_offer(self, sid, udid, factory, sdp, sdp_type):
        self.offers.append(udid)
        return {"sdp": "fake-answer", "type": "answer"}

    def stop(self, sid, udid):
        self.stopped_devices.append(f"{sid}:{udid}")

    def stop_device(self, udid):
        self.stopped_devices.append(udid)

    def stop_sid(self, sid):
        self.stopped_sids.append(sid)

    def shutdown(self):
        pass


class _FakeAdapter:
    def __init__(self, source_id: str, platform: str, devices: list[MobileDevice], fail_discover: bool = False):
        self.source_id = source_id
        self.platform = platform
        self._devices = list(devices)
        self._fail_discover = fail_discover
        self.connected_ids: list[str] = []
        self.disconnected_ids: list[str] = []
        self.webrtc = _FakeWebRTC(enabled=True)

    def is_backend_available(self) -> bool:
        return True

    def discover(self):
        if self._fail_discover:
            raise RuntimeError(f"{self.source_id} down")
        present = set()
        for dev in self._devices:
            dev.source = self.source_id
            present.add(dev.udid)
            state.upsert_device(dev)
        state.remove_missing(present, source=self.source_id)
        return [d for d in state.list_devices() if d.source == self.source_id]

    def connect(self, udid: str):
        self.connected_ids.append(udid)
        dev = state.get_device(udid)
        assert dev is not None
        dev.connected = True
        return dev

    def disconnect(self, udid: str):
        self.disconnected_ids.append(udid)
        dev = state.get_device(udid)
        if dev:
            dev.connected = False

    def controller(self, udid: str):
        return f"ctrl:{self.source_id}:{udid}"

    def check_wda(self, udid: str) -> bool:
        return True

    def shutdown(self) -> None:
        pass


def test_mobile_device_preserves_ios_compatibility():
    ios_dev = IOSDevice(udid="ios-1", name="My iPhone", product_type="iPhone13,4", ios_version="18.0")
    d = ios_dev.to_dict()
    assert d["platform"] == "ios"
    assert d["source"] == "ios"
    assert d["node_id"] == "local"
    assert d["os_version"] == "18.0"
    assert d["marketing"] == "iPhone 12 Pro Max"
    assert "home" in d["capabilities"]

    and_dev = MobileDevice(
        platform="android",
        udid="and-1",
        name="Redmi Note 14 5G",
        product_type="24094RAD4C",
        os_version="16",
        node_id="rog-win",
        source="node:rog-win",
        capabilities=["back", "recent", "home"],
    )
    ad = and_dev.to_dict()
    assert ad["platform"] == "android"
    assert ad["marketing"] == "Redmi Note 14 5G"
    assert ad["node_id"] == "rog-win"
    assert ad["capabilities"] == ["back", "recent", "home"]


def test_scoped_remove_missing_isolates_sources():
    ios_dev = IOSDevice(udid="ios-1", name="iPhone", source="ios")
    and_dev = MobileDevice(platform="android", udid="and-1", name="Redmi", source="android")
    state.upsert_device(ios_dev)
    state.upsert_device(and_dev)

    # An Android rescan returning only {"and-1"} must NOT remove "ios-1".
    gone = state.remove_missing({"and-1"}, source="android")
    assert gone == []
    assert state.get_device("ios-1") is not None
    assert state.get_device("and-1") is not None

    # Removing an Android device by empty android scan leaves iOS intact.
    gone2 = state.remove_missing(set(), source="android")
    assert gone2 == ["and-1"]
    assert state.get_device("and-1") is None
    assert state.get_device("ios-1") is not None


def test_adapter_registry_routing_and_fault_isolation():
    reg = AdapterRegistry({})
    ios_ad = _FakeAdapter("ios", "ios", [IOSDevice(udid="ios-1", name="iPhone")])
    bad_ad = _FakeAdapter("broken", "android", [], fail_discover=True)
    and_ad = _FakeAdapter("android", "android", [MobileDevice(platform="android", udid="and-1", name="K30")])

    reg.register(ios_ad, "ios")
    reg.register(bad_ad, "broken")
    reg.register(and_ad, "android")

    devices = reg.discover()
    assert {d.udid for d in devices} == {"ios-1", "and-1"}

    assert reg.adapter_for("ios-1") is ios_ad
    assert reg.adapter_for("and-1") is and_ad

    reg.connect("ios-1")
    reg.connect("and-1")
    assert ios_ad.connected_ids == ["ios-1"]
    assert and_ad.connected_ids == ["and-1"]
    assert reg.controller("and-1") == "ctrl:android:and-1"

    answer = reg.webrtc.handle_offer("sid-1", "and-1", None, "sdp", "offer")
    assert answer["type"] == "answer"
    assert and_ad.webrtc.offers == ["and-1"]
    assert ios_ad.webrtc.offers == []

    reg.webrtc.stop_sid("sid-1")
    assert ios_ad.webrtc.stopped_sids == ["sid-1"]
    assert and_ad.webrtc.stopped_sids == ["sid-1"]

    with pytest.raises(AppError) as exc:
        reg.adapter_for("missing-device")
    assert exc.value.code == ErrorCode.NO_IOS_DEVICE


def test_init_platform_and_get_adapter_udid_routing():
    reg = init_platform({"IOS_ENABLED": "0"})
    assert isinstance(reg, AdapterRegistry)
    fake = _FakeAdapter("android", "android", [MobileDevice(platform="android", udid="dev-x", name="Pixel")])
    reg.register(fake, "android")
    reg.discover()
    assert get_adapter() is reg
    assert get_adapter("dev-x") is fake
