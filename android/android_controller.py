"""Android controller implementing the same surface as WDAController."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional, Tuple

from android.adb_client import AdbClient
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)

# Android KeyEvent mapping matching public/UI button names.
_BUTTON_KEYCODES = {
    "home": 3,
    "back": 4,
    "recent": 187,
    "appswitch": 187,
    "menu": 82,
    "power": 26,
    "lock": 223,
    "sleep": 223,
    "wake": 224,
    "unlock": 224,
    "volumeup": 24,
    "volumedown": 25,
    "snapshot": 120,
}


class AndroidController:
    def __init__(self, udid: str, adb: AdbClient) -> None:
        self.udid = udid
        self.adb = adb
        self._scrcpy: Any = None
        self._lock = threading.Lock()

    def attach_scrcpy(self, scrcpy_client: Any) -> None:
        with self._lock:
            self._scrcpy = scrcpy_client

    def detach_scrcpy(self) -> None:
        with self._lock:
            self._scrcpy = None

    def _live_scrcpy_control(self):
        with self._lock:
            sc = self._scrcpy
        if sc is not None and getattr(sc, "alive", False) and getattr(sc, "control", None) is not None:
            return sc.control
        return None

    def tap(self, x: int, y: int) -> None:
        ctrl = self._live_scrcpy_control()
        if ctrl is not None:
            try:
                ctrl.touch(int(x), int(y), 0)
                time.sleep(0.02)
                ctrl.touch(int(x), int(y), 1)
                return
            except Exception as exc:  # noqa: BLE001 — fallback to adb
                _log.debug("scrcpy tap failed on %s, falling back to adb: %s", self.udid, exc)
        self.adb.tap(self.udid, x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        ctrl = self._live_scrcpy_control()
        if ctrl is not None:
            try:
                ctrl.swipe(int(x1), int(y1), int(x2), int(y2), duration_ms=max(50, int(duration * 1000)))
                return
            except Exception as exc:  # noqa: BLE001
                _log.debug("scrcpy swipe failed on %s, falling back to adb: %s", self.udid, exc)
        self.adb.swipe(self.udid, x1, y1, x2, y2, duration)

    def double_tap(self, x: int, y: int) -> None:
        self.tap(x, y)
        time.sleep(0.08)
        self.tap(x, y)

    def long_press(self, x: int, y: int, duration: float = 0.8) -> None:
        self.swipe(x, y, x, y, duration=max(0.4, duration))

    def input_text(self, text: str) -> None:
        self.adb.input_text(self.udid, text)

    def home(self) -> None:
        self.press_button("home")

    def lock(self) -> None:
        self.press_button("lock")

    def unlock(self) -> None:
        self.press_button("wake")
        self.adb.keyevent(self.udid, 82)

    def press_button(self, name: str) -> None:
        key = (name or "").strip().lower()
        if key == "rotate":
            ctrl = self._live_scrcpy_control()
            if ctrl is not None and hasattr(ctrl, "rotate_device"):
                ctrl.rotate_device()
                return
            raise AppError(ErrorCode.BAD_REQUEST, "rotate requires active scrcpy control")
        code = _BUTTON_KEYCODES.get(key)
        if code is None:
            raise AppError(ErrorCode.BAD_REQUEST, f"unknown Android button '{name}'")
        ctrl = self._live_scrcpy_control()
        if ctrl is not None:
            try:
                ctrl.keycode(code, 0)
                ctrl.keycode(code, 1)
                return
            except Exception:  # noqa: BLE001
                pass
        self.adb.keyevent(self.udid, code)

    def keyevent(self, code: int) -> None:
        self.adb.keyevent(self.udid, code)

    def set_pasteboard(self, text: str) -> None:
        self.adb.set_clipboard(self.udid, text)

    def get_pasteboard(self) -> str:
        return self.adb.get_clipboard(self.udid)

    def screenshot(self) -> bytes:
        return self.adb.screenshot_png(self.udid)

    def launch_app(self, bundle_id: str) -> None:
        self.adb.launch_app(self.udid, bundle_id)

    def terminate_app(self, bundle_id: str) -> None:
        self.adb.terminate_app(self.udid, bundle_id)

    def get_window_size(self) -> Tuple[int, int]:
        return self.adb.get_screen_size(self.udid)

    def get_orientation(self) -> str:
        return self.adb.get_orientation(self.udid)

    def alert_text(self) -> Optional[str]:
        return None

    def alert_buttons(self) -> list[str]:
        return []

    def alert_accept(self) -> None:
        pass

    def alert_dismiss(self) -> None:
        pass

    def close(self) -> None:
        self.detach_scrcpy()
