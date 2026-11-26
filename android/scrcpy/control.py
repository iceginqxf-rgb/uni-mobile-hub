"""Binary Scrcpy v5.0.1 control channel encoder."""

from __future__ import annotations

import functools
import struct
import time
from typing import Any

from android.scrcpy import const


def _inject(control_type: int):
    def wrapper(fn):
        @functools.wraps(fn)
        def inner(self, *args, **kwargs):
            package = struct.pack(">B", control_type) + fn(self, *args, **kwargs)
            sock = self.parent.control_socket
            if sock is not None:
                with self.parent.control_socket_lock:
                    sock.sendall(package)
            return package

        return inner

    return wrapper


class ScrcpyControl:
    """Encode and send scrcpy binary control packets over ``parent.control_socket``."""

    def __init__(self, parent: Any) -> None:
        self.parent = parent

    @_inject(const.TYPE_INJECT_KEYCODE)
    def keycode(self, keycode: int, action: int = const.ACTION_DOWN, repeat: int = 0, meta_state: int = 0) -> bytes:
        return struct.pack(">Biii", int(action), int(keycode), int(repeat), int(meta_state))

    @_inject(const.TYPE_INJECT_TEXT)
    def text(self, text: str) -> bytes:
        buf = str(text).encode("utf-8")
        return struct.pack(">i", len(buf)) + buf

    @_inject(const.TYPE_INJECT_TOUCH_EVENT)
    def touch(
        self,
        x: int,
        y: int,
        action: int = const.ACTION_DOWN,
        touch_id: int = 0x1234567887654321,
    ) -> bytes:
        w, h = self.parent.resolution or (1080, 1920)
        return struct.pack(
            ">BqiiHHHii",
            int(action),
            int(touch_id),
            int(x),
            int(y),
            int(w),
            int(h),
            0xFFFF,
            1,
            1,
        )

    @_inject(const.TYPE_INJECT_SCROLL_EVENT)
    def scroll(self, x: int, y: int, h_delta: float, v_delta: float) -> bytes:
        w, h_ = self.parent.resolution or (1080, 1920)

        def _to_fixed(raw: float) -> int:
            normalised = max(-1.0, min(1.0, float(raw) / 1200.0))
            return max(-32767, min(32767, int(round(normalised * 32767))))

        return struct.pack(
            ">iiHHhhi",
            int(x),
            int(y),
            int(w),
            int(h_),
            _to_fixed(h_delta),
            _to_fixed(v_delta),
            0,
        )

    @_inject(const.TYPE_BACK_OR_SCREEN_ON)
    def back_or_turn_screen_on(self, action: int = const.ACTION_DOWN) -> bytes:
        return struct.pack(">B", int(action))

    @_inject(const.TYPE_EXPAND_NOTIFICATION_PANEL)
    def expand_notification_panel(self) -> bytes:
        return b""

    @_inject(const.TYPE_EXPAND_SETTINGS_PANEL)
    def expand_settings_panel(self) -> bytes:
        return b""

    @_inject(const.TYPE_COLLAPSE_PANELS)
    def collapse_panels(self) -> bytes:
        return b""

    def set_clipboard(self, text: str, paste: bool = False, sequence: int = const.SEQUENCE_INVALID) -> bool:
        sock = self.parent.control_socket
        if sock is None:
            return False
        buf = str(text).encode("utf-8")
        payload = struct.pack(">BQ?i", const.TYPE_SET_CLIPBOARD, int(sequence), bool(paste), len(buf)) + buf
        if sequence != const.SEQUENCE_INVALID:
            self.parent.clipboard_ack_event.clear()
            self.parent.clipboard_ack_sequence = const.SEQUENCE_INVALID
        with self.parent.control_socket_lock:
            sock.sendall(payload)
        if sequence != const.SEQUENCE_INVALID:
            if not self.parent.clipboard_ack_event.wait(2.0):
                return False
            return self.parent.clipboard_ack_sequence == sequence
        return True

    @_inject(const.TYPE_SET_SCREEN_POWER_MODE)
    def set_screen_power_mode(self, mode: int = const.POWER_MODE_NORMAL) -> bytes:
        return struct.pack(">b", int(mode))

    @_inject(const.TYPE_ROTATE_DEVICE)
    def rotate_device(self) -> bytes:
        return b""

    @_inject(const.TYPE_RESET_VIDEO)
    def reset_video(self) -> bytes:
        return b""

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 200) -> None:
        dx = end_x - start_x
        dy = end_y - start_y
        dist = (dx * dx + dy * dy) ** 0.5
        steps = max(8, min(int(dist // 25), 25))
        step_delay = max(0.005, float(duration_ms) / steps / 1000.0)
        self.touch(start_x, start_y, const.ACTION_DOWN)
        for i in range(1, steps + 1):
            x = int(start_x + dx * i / steps)
            y = int(start_y + dy * i / steps)
            self.touch(x, y, const.ACTION_MOVE)
            time.sleep(step_delay)
        self.touch(end_x, end_y, const.ACTION_UP)
