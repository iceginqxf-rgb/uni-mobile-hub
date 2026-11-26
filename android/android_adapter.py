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
        self.use_scrcpy = str(config.get("ANDROID_USE_SCRCPY", "1")) == "1"
        self.webrtc = WebRTCBridge(config)
        self._controllers: Dict[str, AndroidController] = {}
        self._scrcpy_sessions: Dict[str, object] = {}
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
        if self.use_scrcpy:
            self._ensure_scrcpy_session(udid, dev, ctrl)
        state.touch(udid)
        return dev  # type: ignore[return-value]

    def _ensure_scrcpy_session(self, udid: str, dev: Optional[AndroidDevice], ctrl: AndroidController):
        with self._lock:
            existing = self._scrcpy_sessions.get(udid)
            if existing is not None and getattr(existing, "alive", False):
                ctrl.attach_scrcpy(existing)
                return existing
        from android.scrcpy.session import DEFAULT_SCRCPY_JAR, ScrcpySession

        jar_path = str(self.config.get("SCRCPY_SERVER_PATH") or "") or DEFAULT_SCRCPY_JAR
        session = ScrcpySession(
            self.adb,
            udid,
            server_jar=jar_path,
            server_version=str(self.config.get("SCRCPY_SERVER_VERSION", "5.0.1")),
            max_width=int(self.config.get("SCRCPY_MAX_WIDTH", 1080)),
            bitrate=int(self.config.get("SCRCPY_BITRATE", 8_000_000)),
            max_fps=int(self.config.get("SCRCPY_MAX_FPS", 30)),
        )
        if not session.is_available():
            return None
        try:
            if session.start():
                with self._lock:
                    self._scrcpy_sessions[udid] = session
                ctrl.attach_scrcpy(session)
                if dev and session.resolution:
                    dev.screen_width, dev.screen_height = session.resolution
                return session
        except Exception as exc:  # noqa: BLE001 — fallback cleanly to ADB
            _log.info("scrcpy start skipped/failed for %s (%s); using ADB fallback", udid, exc)
            with suppress(Exception):
                session.stop()
        return None

    def disconnect(self, udid: str) -> None:
        with suppress(Exception):
            self.webrtc.stop_device(udid)
        self.stop_stream(udid)
        with self._lock:
            session = self._scrcpy_sessions.pop(udid, None)
            ctrl = self._controllers.pop(udid, None)
            state.controllers.pop(udid, None)
        if session is not None:
            with suppress(Exception):
                session.stop()
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
        want = (provider_name or self.config.get("ANDROID_SCREEN_PROVIDER", "scrcpy")).lower()
        if want == "scrcpy" and self.use_scrcpy:
            dev = state.get_device(udid)
            ctrl = self.controller(udid)
            session = self._ensure_scrcpy_session(udid, dev, ctrl)  # type: ignore[arg-type]
            if session is not None and getattr(session, "alive", False):
                from android.scrcpy.video_track import ScrcpyFrameProvider

                return ScrcpyFrameProvider(session)
        shot_fps = int(fps or self.config.get("ANDROID_SCREENSHOT_FPS", 6))
        return AdbScreenshotProvider(self.adb, udid, fps=shot_fps)

    def make_webrtc_track(self, udid: str):
        dev = state.get_device(udid)
        if not dev or not dev.connected:
            self.connect(udid)
            dev = state.get_device(udid)
        if self.use_scrcpy:
            ctrl = self.controller(udid)
            session = self._ensure_scrcpy_session(udid, dev, ctrl)  # type: ignore[arg-type]
            if session is not None and getattr(session, "alive", False):
                from android.scrcpy.video_track import ScrcpyVideoTrack

                return ScrcpyVideoTrack(session)
        return None

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
