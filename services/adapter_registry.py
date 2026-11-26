"""Multi-platform adapter registry and routing layer.

Holds one or more platform/node adapters (iOS, local Android, remote Worker
nodes) behind the same surface callers already expect from ``get_adapter()``.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Dict, List, Optional

from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)


class CompositeWebRTC:
    """Route WebRTC signaling calls to the adapter owning ``udid``."""

    def __init__(self, registry: "AdapterRegistry") -> None:
        self._registry = registry

    @property
    def enabled(self) -> bool:
        return any(
            bool(getattr(a, "webrtc", None) and a.webrtc.enabled)
            for a in self._registry.adapters()
        )

    def handle_offer(self, sid: str, udid: str, provider_factory, sdp: str, sdp_type: str):
        adapter = self._registry.adapter_for(udid)
        return adapter.webrtc.handle_offer(sid, udid, provider_factory, sdp, sdp_type)

    def stop(self, sid: str, udid: str) -> None:
        for adapter in self._registry.adapters():
            webrtc = getattr(adapter, "webrtc", None)
            if webrtc is not None:
                with suppress(Exception):
                    webrtc.stop(sid, udid)

    def stop_device(self, udid: str) -> None:
        for adapter in self._registry.adapters():
            webrtc = getattr(adapter, "webrtc", None)
            if webrtc is not None:
                with suppress(Exception):
                    webrtc.stop_device(udid)

    def stop_sid(self, sid: str) -> None:
        for adapter in self._registry.adapters():
            webrtc = getattr(adapter, "webrtc", None)
            if webrtc is not None:
                with suppress(Exception):
                    webrtc.stop_sid(sid)

    def shutdown(self) -> None:
        for adapter in self._registry.adapters():
            webrtc = getattr(adapter, "webrtc", None)
            if webrtc is not None:
                with suppress(Exception):
                    webrtc.shutdown()


class AdapterRegistry:
    """Dispatch device operations across all registered platform/node adapters."""

    platform = "multi"

    def __init__(self, config: dict) -> None:
        self.config = config
        self._adapters: Dict[str, Any] = {}
        self._order: List[str] = []
        self.webrtc = CompositeWebRTC(self)

    def register(self, adapter: Any, source_id: Optional[str] = None) -> None:
        sid = source_id or getattr(adapter, "source_id", None) or getattr(adapter, "platform", "default")
        if hasattr(adapter, "source_id"):
            adapter.source_id = sid
        self._adapters[sid] = adapter
        if sid not in self._order:
            self._order.append(sid)

    def unregister(self, source_id: str) -> None:
        self._adapters.pop(source_id, None)
        if source_id in self._order:
            self._order.remove(source_id)

    def adapters(self) -> List[Any]:
        return [self._adapters[sid] for sid in self._order if sid in self._adapters]

    def get(self, source_id: str) -> Optional[Any]:
        return self._adapters.get(source_id)

    @property
    def goios(self):
        ios = self._adapters.get("ios")
        if ios is not None and hasattr(ios, "goios"):
            return ios.goios
        raise AttributeError("No iOS adapter registered for goios access")

    def adapter_for(self, udid: str) -> Any:
        dev = state.get_device(udid)
        if dev is not None:
            source = getattr(dev, "source", None) or getattr(dev, "platform", None)
            if source and source in self._adapters:
                return self._adapters[source]
        # Fallback: single registered adapter or explicit owns() probe.
        for adapter in self.adapters():
            owns = getattr(adapter, "owns", None)
            if callable(owns) and owns(udid):
                return adapter
        adapters = self.adapters()
        if len(adapters) == 1:
            return adapters[0]
        raise AppError(ErrorCode.NO_IOS_DEVICE, f"Device {udid} not found")

    def is_backend_available(self) -> bool:
        return any(bool(a.is_backend_available()) for a in self.adapters())

    def discover(self):
        for adapter in self.adapters():
            try:
                adapter.discover()
            except Exception as exc:  # noqa: BLE001 — isolate per-adapter failures
                _log.warning(
                    "discover failed on adapter %s: %s",
                    getattr(adapter, "source_id", type(adapter).__name__),
                    exc,
                )
        return state.list_devices()

    def refresh_device(self, udid: str):
        return self.adapter_for(udid).refresh_device(udid)

    def connect(self, udid: str):
        return self.adapter_for(udid).connect(udid)

    def disconnect(self, udid: str) -> None:
        self.adapter_for(udid).disconnect(udid)

    def check_wda(self, udid: str) -> bool:
        return self.adapter_for(udid).check_wda(udid)

    def controller(self, udid: str):
        return self.adapter_for(udid).controller(udid)

    def accessibility(self, udid: str, feature: str, action: str = "toggle") -> dict:
        return self.adapter_for(udid).accessibility(udid, feature, action)

    def set_mjpeg_scaling(self, udid: str, scaling: int) -> dict:
        adapter = self.adapter_for(udid)
        if hasattr(adapter, "set_mjpeg_scaling"):
            return adapter.set_mjpeg_scaling(udid, scaling)
        return {"udid": udid, "scaling": scaling, "applied": False}

    def make_screen_provider(self, udid: str, provider_name: Optional[str] = None, fps: Optional[int] = None):
        return self.adapter_for(udid).make_screen_provider(udid, provider_name, fps=fps)

    def fallback_provider(self, udid: str, fps: Optional[int] = None):
        return self.adapter_for(udid).fallback_provider(udid, fps=fps)

    def make_screen_transport(self, udid: str):
        return self.adapter_for(udid).make_screen_transport(udid)

    def stop_stream(self, udid: str) -> None:
        self.adapter_for(udid).stop_stream(udid)

    def list_apps(self, udid: str, system: bool = False):
        return self.adapter_for(udid).list_apps(udid, system=system)

    def install_app(self, udid: str, path: str):
        return self.adapter_for(udid).install_app(udid, path)

    def uninstall_app(self, udid: str, bundle_id: str):
        return self.adapter_for(udid).uninstall_app(udid, bundle_id)

    def file_tree(self, udid: str, path: str = ".", app: Optional[str] = None):
        return self.adapter_for(udid).file_tree(udid, path=path, app=app)

    def file_pull_to_temp(self, udid: str, src_path: str, app: Optional[str] = None):
        return self.adapter_for(udid).file_pull_to_temp(udid, src_path, app=app)

    def file_push(self, udid: str, local_path: str, dst_path: str, app: Optional[str] = None):
        return self.adapter_for(udid).file_push(udid, local_path, dst_path, app=app)

    def log_popen(self, udid: str, **kwargs):
        return self.adapter_for(udid).log_popen(udid, **kwargs)

    def collect_device_info(self, udid: str) -> dict:
        adapter = self.adapter_for(udid)
        fn = getattr(adapter, "collect_device_info", None)
        if callable(fn):
            return fn(udid)
        from services import device_info

        return device_info.collect(udid)

    def shutdown(self) -> None:
        for adapter in self.adapters():
            with suppress(Exception):
                adapter.shutdown()
