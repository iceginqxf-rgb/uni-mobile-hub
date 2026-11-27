"""App management: list / install / uninstall installed apps & running tasks.

Backed by go-ios (usbmux/installation-proxy) — independent of WDA and the RSD
tunnel, so it works as soon as the device is paired — plus DVT proclist for
live running applications on iOS 17+.
"""

from __future__ import annotations

from services import get_adapter
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)


class IOSAppService:
    @staticmethod
    def _adapter_or_goios(udid: str):
        adapter = get_adapter(udid)
        if hasattr(adapter, "list_apps") and getattr(adapter, "platform", "ios") != "ios":
            return adapter, None
        if not (getattr(adapter, "use_goios", False) and adapter.goios.is_available()):
            raise AppError(ErrorCode.BAD_REQUEST,
                           "app management requires go-ios, which is not available")
        return adapter, adapter.goios

    @classmethod
    def list_apps(cls, udid: str, system: bool = False) -> dict:
        adapter, goios = cls._adapter_or_goios(udid)
        if goios is None:
            return adapter.list_apps(udid, system=system)
        return {"apps": goios.list_apps(udid, system=system)}

    @classmethod
    def running_apps(cls, udid: str, include_system: bool = False) -> dict:
        adapter = get_adapter(udid)
        if getattr(adapter, "platform", "ios") != "ios":
            if hasattr(adapter, "running_apps"):
                return adapter.running_apps(udid, include_system=include_system)
            return {"apps": [], "foreground_bundle_id": ""}

        fg_bid = ""
        try:
            ctrl = adapter.controller(udid)
            active = ctrl.active_app_info() or {}
            fg_bid = str(active.get("bundleId") or "").strip()
        except Exception:
            fg_bid = ""

        from ios.dvt_metrics import list_running_apps

        apps = list_running_apps(
            udid,
            foreground_bundle_id=fg_bid,
            include_system=include_system,
        )
        return {"apps": apps, "foreground_bundle_id": fg_bid}

    @classmethod
    def uninstall(cls, udid: str, bundle_id: str) -> dict:
        adapter, goios = cls._adapter_or_goios(udid)
        if goios is None:
            return adapter.uninstall_app(udid, bundle_id)
        ok, msg = goios.uninstall_app(udid, bundle_id)
        if not ok:
            raise AppError(ErrorCode.BAD_REQUEST, f"uninstall failed: {msg[:200]}",
                           {"bundle_id": bundle_id})
        _log.info("uninstalled %s from %s", bundle_id, udid[:12])
        return {"bundle_id": bundle_id, "uninstalled": True}

    @classmethod
    def install(cls, udid: str, ipa_path: str) -> dict:
        adapter, goios = cls._adapter_or_goios(udid)
        if goios is None:
            return adapter.install_app(udid, ipa_path)
        ok, msg = goios.install_app(udid, ipa_path)
        if not ok:
            raise AppError(ErrorCode.BAD_REQUEST, f"install failed: {msg[:300]}")
        _log.info("installed ipa on %s", udid[:12])
        return {"installed": True, "detail": msg[:200]}
