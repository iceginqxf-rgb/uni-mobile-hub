"""AndroidAdapter — local ADB + optional Scrcpy implementation of the device adapter."""

from __future__ import annotations

import threading
from contextlib import suppress
from typing import Dict, List, Optional

from android.adb_client import AdbClient
from android.android_controller import AndroidController
from android.device_models import AndroidDevice
from android.screen_provider import AdbScreenshotProvider
from services.runtime_state import state
from services.webrtc_bridge import WebRTCBridge
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)


class AndroidAdapter:
    platform = "android"
    source_id = "android"

    def __init__(self, config: dict) -> None:
        self.config = config
        self.source_id = "android"
        self.adb = AdbClient(
            adb_bin=str(config.get("ANDROID_ADB_BIN") or ""),
            command_timeout=int(config.get("ANDROID_COMMAND_TIMEOUT", 15)),
        )
        self.webrtc = WebRTCBridge(config)
        self._controllers: Dict[str, AndroidController] = {}
        self._lock = threading.RLock()

    def is_backend_available(self) -> bool:
        return self.adb.is_available()

    def discover(self) -> List[AndroidDevice]:
        if not self.is_backend_available():
            return []
        present = set()
        found: List[AndroidDevice] = []
        for item in self.adb.list_devices():
            udid = item["udid"]
            dev = AndroidDevice(
                udid=udid,
                name=item.get("name") or udid,
                product_type=item.get("product_type") or "",
                os_version=item.get("os_version") or "",
                screen_width=item.get("screen_width"),
                screen_height=item.get("screen_height"),
                trusted=True,
                node_id="local",
                source=self.source_id,
            )
            present.add(udid)
            found.append(state.upsert_device(dev))
        for gone_id in state.remove_missing(present, source=self.source_id):
            _log.info("android device unplugged, tearing down: %s", gone_id)
            with suppress(Exception):
                self.disconnect(gone_id)
        return found

    def refresh_device(self, udid: str) -> AndroidDevice:
        self.discover()
        dev = state.get_device(udid)
        if not dev or dev.source != self.source_id:
            raise AppError(ErrorCode.NO_IOS_DEVICE, f"Android device {udid} not found")
        return dev  # type: ignore[return-value]

    def connect(self, udid: str) -> AndroidDevice:
        dev = state.get_device(udid)
        if not dev:
            self.discover()
            dev = state.get_device(udid)
        if not dev:
            raise AppError(ErrorCode.NO_IOS_DEVICE, f"Device {udid} not found")
        ctrl = self.controller(udid)
        try:
            w, h = ctrl.get_window_size()
            if w and h:
                dev.screen_width, dev.screen_height = w, h
            dev.orientation = ctrl.get_orientation()
        except AppError:
            pass
        dev.connected = True
        state.touch(udid)
        return dev  # type: ignore[return-value]

    def disconnect(self, udid: str) -> None:
        with suppress(Exception):
            self.webrtc.stop_device(udid)
        self.stop_stream(udid)
        with self._lock:
            ctrl = self._controllers.pop(udid, None)
            state.controllers.pop(udid, None)
        if ctrl is not None:
            with suppress(Exception):
                ctrl.close()
        dev = state.get_device(udid)
        if dev:
            dev.connected = False
            dev.streaming = False
            dev.screen_provider = None
        state.forget(udid)

    def check_wda(self, udid: str) -> bool:
        dev = state.get_device(udid)
        return bool(dev and dev.connected)

    def controller(self, udid: str) -> AndroidController:
        dev = state.get_device(udid)
        if not dev:
            raise AppError(ErrorCode.NO_IOS_DEVICE, f"Device {udid} not found")
        with self._lock:
            ctrl = self._controllers.get(udid)
            if ctrl is None:
                ctrl = AndroidController(udid, self.adb)
                self._controllers[udid] = ctrl
                state.controllers[udid] = ctrl
            return ctrl

    @staticmethod
    def accessibility(udid: str, feature: str, action: str = "toggle") -> dict:
        raise AppError(ErrorCode.BAD_REQUEST, "Accessibility toggles are only supported on iOS devices")

    def make_screen_provider(
        self, udid: str, provider_name: Optional[str] = None, fps: Optional[int] = None
    ):
        shot_fps = int(fps or self.config.get("ANDROID_SCREENSHOT_FPS", 6))
        return AdbScreenshotProvider(self.adb, udid, fps=shot_fps)

    def fallback_provider(self, udid: str, fps: Optional[int] = None):
        shot_fps = int(fps or self.config.get("ANDROID_SCREENSHOT_FPS", 5))
        return AdbScreenshotProvider(self.adb, udid, fps=shot_fps)

    @staticmethod
    def make_screen_transport(udid: str):
        raise AppError(ErrorCode.BAD_REQUEST, "HEVC RSD transport is iOS-only")

    @staticmethod
    def stop_stream(udid: str) -> None:
        session = state.streams.get(udid)
        if session and hasattr(session, "stop"):
            session.stop()

    def list_apps(self, udid: str, system: bool = False) -> dict:
        return {"apps": self.adb.list_apps(udid, system=system)}

    def install_app(self, udid: str, path: str) -> dict:
        ok, msg = self.adb.install_apk(udid, path)
        if not ok:
            raise AppError(ErrorCode.BAD_REQUEST, f"apk install failed: {msg[:300]}")
        return {"installed": True, "detail": msg[:200]}

    def uninstall_app(self, udid: str, bundle_id: str) -> dict:
        ok, msg = self.adb.uninstall_app(udid, bundle_id)
        if not ok:
            raise AppError(ErrorCode.BAD_REQUEST, f"apk uninstall failed: {msg[:200]}", {"bundle_id": bundle_id})
        return {"bundle_id": bundle_id, "uninstalled": True}

    def file_tree(self, udid: str, path: str = ".", app: Optional[str] = None) -> dict:
        target = "/sdcard" if path in (".", "", "/") else path
        return {"path": target, "app": app, "entries": self.adb.list_dir(udid, target)}

    def file_pull_to_temp(self, udid: str, src_path: str, app: Optional[str] = None) -> str:
        return self.adb.pull_to_temp(udid, src_path)

    def file_push(self, udid: str, local_path: str, dst_path: str, app: Optional[str] = None) -> dict:
        self.adb.push_file(udid, local_path, dst_path)
        return {"dst_path": dst_path, "pushed": True}

    def log_popen(self, udid: str, level: str = "I", **_kwargs):
        return self.adb.logcat_popen(udid, level=level)

    def collect_device_info(self, udid: str) -> dict:
        return self.adb.collect_info(udid)

    def shutdown(self) -> None:
        with suppress(Exception):
            self.webrtc.shutdown()
        for udid in list(self._controllers.keys()):
            with suppress(Exception):
                self.disconnect(udid)
