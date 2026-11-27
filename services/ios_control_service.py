"""Control business logic: maps browser-space coords to device tap/swipe."""

from __future__ import annotations

from typing import Tuple

from services import get_adapter
from services.runtime_state import state
from services.request_validators import as_number, map_display_to_device, require
from services.sync_service import sync_service
from utils.app_errors import AppError, ErrorCode
from utils.image_utils import to_data_url
from utils.logging_setup import get_logger

_log = get_logger(__name__)


class IOSControlService:
    @staticmethod
    def _device_size(udid: str, controller) -> Tuple[int, int]:
        dev = state.get_device(udid)
        if dev and dev.screen_width and dev.screen_height:
            return dev.screen_width, dev.screen_height
        w, h = controller.get_window_size()
        if dev and w and h:
            dev.screen_width, dev.screen_height = w, h
        if not w or not h:
            raise AppError(
                ErrorCode.COORDINATE_MAPPING_FAILED,
                "Unknown device screen size; cannot map coordinates",
            )
        return w, h

    def _resolve_point(self, udid: str, controller, body: dict, xk: str, yk: str) -> Tuple[int, int]:
        """Resolve normalized (nx/ny), display_width/height, or raw pixel coords."""
        nkx = "n" + xk
        nky = "n" + yk
        if body.get(nkx) is not None and body.get(nky) is not None:
            nx = max(0.0, min(1.0, as_number(body[nkx], nkx)))
            ny = max(0.0, min(1.0, as_number(body[nky], nky)))
            dev_w, dev_h = self._device_size(udid, controller)
            tx = max(0, min(dev_w - 1, int(round(nx * dev_w))))
            ty = max(0, min(dev_h - 1, int(round(ny * dev_h))))
            return tx, ty

        x = as_number(body[xk], xk)
        y = as_number(body[yk], yk)
        dw, dh = body.get("display_width"), body.get("display_height")
        if dw and dh:
            dev_w, dev_h = self._device_size(udid, controller)
            dev = state.get_device(udid)
            orient = (dev.orientation if dev else "PORTRAIT") or "PORTRAIT"
            return map_display_to_device(
                x, y, as_number(dw, "display_width"), as_number(dh, "display_height"),
                dev_w, dev_h, orient,
            )
        return int(round(x)), int(round(y))

    def _normalized_xy(self, udid: str, controller, x: int, y: int) -> Tuple[float, float]:
        """Best-effort pixel → 0..1 normalization for cross-OS sync fanout."""
        try:
            w, h = self._device_size(udid, controller)
            return max(0.0, min(1.0, x / float(w))), max(0.0, min(1.0, y / float(h)))
        except Exception:
            return 0.5, 0.5

    def tap(self, udid: str, body: dict, *, skip_sync: bool = False) -> dict:
        if body.get("nx") is None or body.get("ny") is None:
            require(body, "x", "y")
        controller = get_adapter().controller(udid)
        x, y = self._resolve_point(udid, controller, body, "x", "y")
        controller.tap(x, y)
        if not skip_sync and sync_service.get_slaves(udid):
            nx, ny = self._normalized_xy(udid, controller, x, y)
            sync_service.fanout(udid, "tap", {"nx": nx, "ny": ny})
        return {"x": x, "y": y}

    def swipe(self, udid: str, body: dict, *, skip_sync: bool = False) -> dict:
        if any(body.get(k) is None for k in ("nx1", "ny1", "nx2", "ny2")):
            require(body, "x1", "y1", "x2", "y2")
        controller = get_adapter().controller(udid)
        x1, y1 = self._resolve_point(udid, controller, body, "x1", "y1")
        x2, y2 = self._resolve_point(udid, controller, body, "x2", "y2")
        duration = float(body.get("duration", 0.3) or 0.3)
        hold_end = float(body.get("hold_end", 0) or 0)
        if hold_end > 0:
            try:
                controller.swipe(x1, y1, x2, y2, duration, hold_end=hold_end)
            except TypeError:
                controller.swipe(x1, y1, x2, y2, duration)
        else:
            controller.swipe(x1, y1, x2, y2, duration)
        if not skip_sync and sync_service.get_slaves(udid):
            nx1, ny1 = self._normalized_xy(udid, controller, x1, y1)
            nx2, ny2 = self._normalized_xy(udid, controller, x2, y2)
            sync_service.fanout(udid, "swipe", {
                "nx1": nx1, "ny1": ny1, "nx2": nx2, "ny2": ny2, "duration": duration,
            })
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration}

    def double_tap(self, udid: str, body: dict, *, skip_sync: bool = False) -> dict:
        if body.get("nx") is None or body.get("ny") is None:
            require(body, "x", "y")
        controller = get_adapter().controller(udid)
        x, y = self._resolve_point(udid, controller, body, "x", "y")
        controller.double_tap(x, y)
        if not skip_sync and sync_service.get_slaves(udid):
            nx, ny = self._normalized_xy(udid, controller, x, y)
            sync_service.fanout(udid, "double_tap", {"nx": nx, "ny": ny})
        return {"x": x, "y": y}

    def long_press(self, udid: str, body: dict, *, skip_sync: bool = False) -> dict:
        if body.get("nx") is None or body.get("ny") is None:
            require(body, "x", "y")
        controller = get_adapter().controller(udid)
        x, y = self._resolve_point(udid, controller, body, "x", "y")
        duration = float(body.get("duration", 0.8) or 0.8)
        controller.long_press(x, y, duration)
        if not skip_sync and sync_service.get_slaves(udid):
            nx, ny = self._normalized_xy(udid, controller, x, y)
            sync_service.fanout(udid, "long_press", {"nx": nx, "ny": ny, "duration": duration})
        return {"x": x, "y": y, "duration": duration}

    @staticmethod
    def alert(udid: str) -> dict:
        controller = get_adapter().controller(udid)
        text = controller.alert_text()
        return {
            "present": text is not None,
            "text": text or "",
            "buttons": controller.alert_buttons() if text is not None else [],
        }

    @staticmethod
    def alert_action(udid: str, action: str) -> dict:
        action = (action or "").strip().lower()
        controller = get_adapter().controller(udid)
        if action == "accept":
            controller.alert_accept()
        elif action == "dismiss":
            controller.alert_dismiss()
        else:
            raise AppError(ErrorCode.BAD_REQUEST, f"unknown alert action '{action}' (accept/dismiss)")
        return {"action": action}

    @staticmethod
    def input_text(udid: str, body: dict, *, skip_sync: bool = False) -> dict:
        require(body, "text")
        text = str(body["text"])
        controller = get_adapter().controller(udid)
        controller.input_text(text)
        if not skip_sync and sync_service.get_slaves(udid):
            sync_service.fanout(udid, "input_text", {"text": text})
        return {"length": len(text)}

    # Keyboard keys → the control chars WDA's /wda/keys understands (and Android
    # AdbClient translates back to keyevents; Android nav keys map directly).
    _KEYS = {"backspace": "\b", "delete": "\b", "enter": "\n", "return": "\n",
             "tab": "\t", "space": " "}
    _NAV_KEYS = {"back", "home", "recent", "appswitch"}

    @classmethod
    def key(cls, udid: str, name: str, *, skip_sync: bool = False) -> dict:
        name = (name or "").strip().lower()
        if name in cls._NAV_KEYS:
            get_adapter().controller(udid).press_button(name)
            if not skip_sync and sync_service.get_slaves(udid):
                sync_service.fanout(udid, "key", {"name": name})
            return {"key": name}
        ch = cls._KEYS.get(name)
        if ch is None:
            raise AppError(ErrorCode.BAD_REQUEST,
                           f"unknown key '{name}' (backspace/enter/tab/space/back/home/recent)")
        get_adapter().controller(udid).input_text(ch)
        if not skip_sync and sync_service.get_slaves(udid):
            sync_service.fanout(udid, "key", {"name": name})
        return {"key": name}

    # Hardware buttons. Keys are the public (UI) names; values map to WDA or AndroidController.
    _PRESS = {"volumeup": "volumeUp", "volumedown": "volumeDown", "snapshot": "snapshot"}
    _DIRECT_BUTTONS = {"back", "recent", "appswitch", "power", "wake", "sleep", "rotate", "menu"}

    @classmethod
    def button(cls, udid: str, name: str, *, skip_sync: bool = False) -> dict:
        name = (name or "").strip().lower()
        controller = get_adapter().controller(udid)
        if name == "home":
            controller.home()
        elif name == "lock":
            controller.lock()
        elif name == "unlock":
            controller.unlock()
        elif name in cls._PRESS:
            controller.press_button(cls._PRESS[name])
        elif name in cls._DIRECT_BUTTONS:
            controller.press_button(name)
        else:
            raise AppError(
                ErrorCode.BAD_REQUEST,
                f"unknown button '{name}' (home/back/recent/lock/unlock/power/wake/rotate/volumeup/volumedown)",
            )
        if name == "rotate":
            cls._refresh_geometry(udid, controller)
        if not skip_sync and sync_service.get_slaves(udid):
            sync_service.fanout(udid, "button", {"name": name})
        return {"button": name}

    @staticmethod
    def _refresh_geometry(udid: str, controller) -> None:
        dev = state.get_device(udid)
        if not dev:
            return
        try:
            w, h = controller.get_window_size()
            orient = controller.get_orientation()
            if (w and h and (dev.screen_width != w or dev.screen_height != h)) or (
                orient and dev.orientation != orient
            ):
                if w and h:
                    dev.screen_width, dev.screen_height = int(w), int(h)
                if orient:
                    dev.orientation = orient
                from services.event_bus import emit

                emit("devices:changed", {"reason": "rotated", "udid": udid})
        except Exception:
            pass

    @staticmethod
    def accessibility(udid: str, feature: str, action: str = "toggle") -> dict:
        return get_adapter().accessibility(udid, feature, action)

    @staticmethod
    def set_clipboard(udid: str, text: str) -> dict:
        get_adapter().controller(udid).set_pasteboard(text)
        return {"length": len(text)}

    @staticmethod
    def get_clipboard(udid: str) -> dict:
        # iOS returns empty when WDA isn't foreground; flag that so the UI can
        # explain instead of looking broken.
        text = get_adapter().controller(udid).get_pasteboard()
        return {"text": text, "available": bool(text)}

    @staticmethod
    def screenshot(udid: str, as_base64: bool = True) -> dict:
        from utils.image_utils import to_jpeg

        controller = get_adapter().controller(udid)
        png = controller.screenshot()
        jpeg = to_jpeg(png)
        if as_base64:
            return {"image": to_data_url(jpeg), "mime": "image/jpeg"}
        return {"bytes": jpeg}

    @staticmethod
    def launch_app(udid: str, bundle_id: str) -> dict:
        get_adapter().controller(udid).launch_app(bundle_id)
        return {"bundle_id": bundle_id}

    @staticmethod
    def terminate_app(udid: str, bundle_id: str) -> dict:
        get_adapter().controller(udid).terminate_app(bundle_id)
        return {"bundle_id": bundle_id}


ios_control_service = IOSControlService()
