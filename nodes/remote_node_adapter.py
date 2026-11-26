"""RemoteNodeAdapter — aggregate Android/iOS Worker nodes onto a single Hub."""

from __future__ import annotations

import base64
import os
import tempfile
import threading
import time
import urllib.parse
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple

import httpx

from android.adb_client import AdbClient
from android.device_models import AndroidDevice
from ios.screen_provider.base_provider import BaseScreenProvider
from nodes.node_config import RemoteNodeConfig
from services.device_models import MobileDevice
from services.runtime_state import state
from services.webrtc_bridge import WebRTCBridge
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)

_ANDROID_BUTTON_KEYCODES = {
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


class RemoteNodeClient:
    """HTTP client targeting a remote ``uni-mobile-hub`` or ``WebAppFlaskscrcpy`` node."""

    def __init__(self, node: RemoteNodeConfig, transport: Optional[httpx.BaseTransport] = None) -> None:
        self.node = node
        self._lock = threading.Lock()
        self._client = httpx.Client(
            base_url=node.url,
            timeout=node.timeout,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        with suppress(Exception):
            self._client.close()

    def login(self) -> None:
        if not (self.node.username and self.node.password):
            return
        resp = self._client.post(
            "/api/auth/login",
            json={"username": self.node.username, "password": self.node.password},
        )
        if resp.status_code >= 400:
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                f"Remote node {self.node.id} login failed ({resp.status_code})",
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool = True,
        **kwargs,
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.node.token:
            headers.setdefault("Authorization", f"Bearer {self.node.token}")
            headers.setdefault("X-Node-Token", self.node.token)

        for attempt in range(2):
            try:
                resp = self._client.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"Remote node {self.node.id} unreachable: {exc}",
                ) from exc

            if resp.status_code == 401 and attempt == 0 and self.node.password:
                self.login()
                continue
            if resp.status_code >= 400:
                raise AppError(
                    ErrorCode.BAD_REQUEST,
                    f"Remote node {self.node.id} HTTP {resp.status_code} on {method} {path}: {resp.text[:200]}",
                )
            if not expect_json:
                return resp
            try:
                return resp.json()
            except ValueError:
                return {}
        raise AppError(ErrorCode.UNAUTHORIZED, f"Remote node {self.node.id} unauthorized")


class RemoteSnapshotProvider(BaseScreenProvider):
    """Stream JPEG snapshots from a remote Worker node."""

    name = "remote-snapshot"

    def __init__(self, client: RemoteNodeClient, remote_udid: str, fps: int = 8) -> None:
        self.client = client
        self.remote_udid = remote_udid
        self.fps = max(1, min(20, int(fps)))
        self._running = False
        self._healthy = False
        self._frames = 0
        self._last_tick = 0.0

    def start(self) -> None:
        self._running = True
        self._healthy = True

    def stop(self) -> None:
        self._running = False
        self._healthy = False

    def read_frame(self) -> Optional[bytes]:
        if not self._running:
            return None
        interval = 1.0 / self.fps
        now = time.monotonic()
        wait = interval - (now - self._last_tick)
        if wait > 0:
            time.sleep(wait)
        self._last_tick = time.monotonic()
        try:
            data = _fetch_remote_screenshot(self.client, self.remote_udid, quality=75)
            self._frames += 1
            self._healthy = True
            return data
        except AppError:
            self._healthy = False
            return None

    def health(self) -> bool:
        return self._running and self._healthy


def _fetch_remote_screenshot(client: RemoteNodeClient, remote_udid: str, quality: int = 80) -> bytes:
    if client.node.type == "scrcpy":
        resp = client.request(
            "GET",
            f"/api/snapshot?device_id={urllib.parse.quote(remote_udid)}&quality={int(quality)}",
            expect_json=False,
        )
        return bytes(resp.content)

    body = client.request(
        "GET",
        f"/api/devices/{urllib.parse.quote(remote_udid)}/screenshot",
    )
    img_url = ((body.get("data") or {}).get("image") or "") if isinstance(body, dict) else ""
    if "," in img_url:
        _, b64 = img_url.split(",", 1)
        return base64.b64decode(b64)
    raise AppError(ErrorCode.WDA_REQUEST_FAILED, f"Remote node {client.node.id} returned empty screenshot")


class RemoteNodeController:
    """Controller delegating operations to a remote Worker node (with optional SSH ADB fallback)."""

    def __init__(self, adapter: "RemoteNodeAdapter", udid: str, remote_udid: str) -> None:
        self.adapter = adapter
        self.udid = udid
        self.remote_udid = remote_udid
        self.client = adapter.client
        self.node = adapter.node

    def _uni(self, method: str, subpath: str, **kwargs):
        q = urllib.parse.quote(self.remote_udid)
        return self.client.request(method, f"/api/devices/{q}{subpath}", **kwargs)

    def _scrcpy(self, method: str, subpath: str, **kwargs):
        q = urllib.parse.quote(self.remote_udid)
        return self.client.request(method, f"/api/device/{q}{subpath}", **kwargs)

    def _require_ssh_adb(self) -> AdbClient:
        if self.adapter.ssh_adb is None:
            raise AppError(
                ErrorCode.BAD_REQUEST,
                f"Coordinate/text action on scrcpy node '{self.node.id}' requires ssh_host or a uni-mobile-hub worker",
            )
        return self.adapter.ssh_adb

    def tap(self, x: int, y: int) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/tap", json={"x": int(x), "y": int(y)})
            return
        self._require_ssh_adb().tap(self.remote_udid, int(x), int(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/swipe", json={"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2), "duration": duration})
            return
        self._require_ssh_adb().swipe(self.remote_udid, int(x1), int(y1), int(x2), int(y2), duration)

    def double_tap(self, x: int, y: int) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/doubletap", json={"x": int(x), "y": int(y)})
            return
        adb = self._require_ssh_adb()
        adb.tap(self.remote_udid, int(x), int(y))
        time.sleep(0.08)
        adb.tap(self.remote_udid, int(x), int(y))

    def long_press(self, x: int, y: int, duration: float = 0.8) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/longpress", json={"x": int(x), "y": int(y), "duration": duration})
            return
        self._require_ssh_adb().swipe(self.remote_udid, int(x), int(y), int(x), int(y), max(0.4, duration))

    def input_text(self, text: str) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/input", json={"text": str(text)})
            return
        self._require_ssh_adb().input_text(self.remote_udid, str(text))

    def home(self) -> None:
        self.press_button("home")

    def lock(self) -> None:
        self.press_button("lock")

    def unlock(self) -> None:
        self.press_button("unlock")

    def press_button(self, name: str) -> None:
        key = (name or "").strip().lower()
        if self.node.type == "uni":
            self._uni("POST", "/button", json={"name": key})
            return
        if key == "rotate":
            self._scrcpy("POST", "/rotate", json={"target": 1})
            return
        code = _ANDROID_BUTTON_KEYCODES.get(key)
        if code is None:
            raise AppError(ErrorCode.BAD_REQUEST, f"unknown Android button '{name}'")
        self._scrcpy("POST", "/keyevent", json={"code": code})

    def screenshot(self) -> bytes:
        try:
            return _fetch_remote_screenshot(self.client, self.remote_udid, quality=85)
        except AppError:
            if self.adapter.ssh_adb is not None:
                return self.adapter.ssh_adb.screenshot_png(self.remote_udid)
            raise

    def set_pasteboard(self, text: str) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/clipboard", json={"text": text})
            return
        self._require_ssh_adb().set_clipboard(self.remote_udid, text)

    def get_pasteboard(self) -> str:
        if self.node.type == "uni":
            res = self._uni("GET", "/clipboard")
            return str(((res.get("data") or {}).get("text")) or "")
        return self._require_ssh_adb().get_clipboard(self.remote_udid)

    def launch_app(self, bundle_id: str) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/launch", json={"bundle_id": bundle_id})
            return
        self._require_ssh_adb().launch_app(self.remote_udid, bundle_id)

    def terminate_app(self, bundle_id: str) -> None:
        if self.node.type == "uni":
            self._uni("POST", "/terminate", json={"bundle_id": bundle_id})
            return
        self._require_ssh_adb().terminate_app(self.remote_udid, bundle_id)

    def get_window_size(self) -> Tuple[int, int]:
        dev = state.get_device(self.udid)
        if dev and dev.screen_width and dev.screen_height:
            return int(dev.screen_width), int(dev.screen_height)
        if self.adapter.ssh_adb is not None:
            return self.adapter.ssh_adb.get_screen_size(self.remote_udid)
        raise AppError(ErrorCode.COORDINATE_MAPPING_FAILED, f"Unknown screen size for remote {self.udid}")

    def get_orientation(self) -> str:
        dev = state.get_device(self.udid)
        return (dev.orientation if dev else "PORTRAIT") or "PORTRAIT"

    def alert_text(self) -> Optional[str]:
        return None

    def alert_buttons(self) -> List[str]:
        return []

    def close(self) -> None:
        pass


class RemoteNodeAdapter:
    """Adapter managing devices hosted on a remote Worker node."""

    def __init__(
        self,
        config: dict,
        node: RemoteNodeConfig,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.config = config
        self.node = node
        self.source_id = f"node:{node.id}"
        self.platform = "android" if node.type == "scrcpy" else "multi"
        self.client = RemoteNodeClient(node, transport=transport)
        self.ssh_adb = AdbClient(adb_bin=node.adb_bin, ssh_host=node.ssh_host) if node.ssh_host else None
        self.webrtc = WebRTCBridge(config)
        self._controllers: Dict[str, RemoteNodeController] = {}
        self._remote_ids: Dict[str, str] = {}
        self._lock = threading.RLock()

    def is_backend_available(self) -> bool:
        return bool(self.node.url)

    def owns(self, udid: str) -> bool:
        with self._lock:
            return udid in self._remote_ids

    def _resolve_remote_id(self, udid: str) -> str:
        with self._lock:
            if udid in self._remote_ids:
                return self._remote_ids[udid]
        dev = state.get_device(udid)
        ep = getattr(dev, "stream_endpoint", None) if dev else None
        if isinstance(ep, dict) and ep.get("remote_udid"):
            return str(ep["remote_udid"])
        return udid

    def discover(self) -> List[MobileDevice]:
        try:
            items = self._fetch_remote_devices()
        except Exception as exc:  # noqa: BLE001 — isolate node outages cleanly
            _log.warning("remote node '%s' discover failed: %s", self.node.id, exc)
            for gone_id in state.remove_missing(set(), source=self.source_id):
                with self._lock:
                    self._remote_ids.pop(gone_id, None)
                    self._controllers.pop(gone_id, None)
            return []

        present: set[str] = set()
        out: List[MobileDevice] = []
        for dev in items:
            present.add(dev.udid)
            with self._lock:
                self._remote_ids[dev.udid] = str(dev.stream_endpoint.get("remote_udid") or dev.udid)  # type: ignore[union-attr]
            out.append(state.upsert_device(dev))

        for gone_id in state.remove_missing(present, source=self.source_id):
            with self._lock:
                self._remote_ids.pop(gone_id, None)
                self._controllers.pop(gone_id, None)
        return out

    def _fetch_remote_devices(self) -> List[MobileDevice]:
        if self.node.type == "scrcpy":
            body = self.client.request("GET", "/api/devices")
            serials = body.get("devices") or []
            names = body.get("names") or {}
            geom = body.get("geometry") or {}
            items: List[MobileDevice] = []
            for serial in serials:
                g = geom.get(serial) or {}
                items.append(
                    AndroidDevice(
                        udid=serial,
                        name=str(names.get(serial) or serial),
                        os_version="Android",
                        screen_width=g.get("width"),
                        screen_height=g.get("height"),
                        trusted=True,
                        node_id=self.node.id,
                        source=self.source_id,
                        stream_endpoint={
                            "mode": "remote_scrcpy",
                            "node_id": self.node.id,
                            "base_url": self.node.public_url,
                            "remote_udid": serial,
                        },
                    )
                )
            return items

        body = self.client.request("GET", "/api/devices?rescan=1")
        raw_devs = (body.get("data") or {}).get("devices") or []
        items = []
        for d in raw_devs:
            raw_id = str(d.get("udid") or "")
            if not raw_id:
                continue
            plat = str(d.get("platform") or "android")
            items.append(
                MobileDevice(
                    platform=plat,
                    udid=raw_id,
                    name=str(d.get("name") or raw_id),
                    product_type=str(d.get("product_type") or ""),
                    ios_version=str(d.get("ios_version") or d.get("os_version") or ""),
                    os_version=str(d.get("os_version") or d.get("ios_version") or ""),
                    screen_width=d.get("screen_width"),
                    screen_height=d.get("screen_height"),
                    trusted=bool(d.get("trusted", True)),
                    node_id=self.node.id,
                    source=self.source_id,
                    capabilities=list(d.get("capabilities") or []),
                    stream_endpoint={
                        "mode": "remote_uni",
                        "node_id": self.node.id,
                        "base_url": self.node.public_url,
                        "remote_udid": raw_id,
                    },
                )
            )
        return items

    def refresh_device(self, udid: str) -> MobileDevice:
        self.discover()
        dev = state.get_device(udid)
        if not dev or dev.source != self.source_id:
            raise AppError(ErrorCode.NO_IOS_DEVICE, f"Remote device {udid} not found")
        return dev

    def connect(self, udid: str) -> MobileDevice:
        dev = state.get_device(udid)
        if not dev:
            self.discover()
            dev = state.get_device(udid)
        if not dev:
            raise AppError(ErrorCode.NO_IOS_DEVICE, f"Device {udid} not found")

        remote_id = self._resolve_remote_id(udid)
        with suppress(AppError):
            self.client.request("POST", "/api/reservations", json={"device_id": remote_id})
        if self.node.type == "scrcpy":
            self.client.request("POST", "/api/start", json={"device_id": remote_id})
        else:
            q = urllib.parse.quote(remote_id)
            self.client.request("POST", f"/api/devices/{q}/connect", json={})

        dev.connected = True
        state.touch(udid)
        return dev

    def disconnect(self, udid: str) -> None:
        with suppress(Exception):
            self.webrtc.stop_device(udid)
        self.stop_stream(udid)
        remote_id = self._resolve_remote_id(udid)
        with suppress(AppError):
            if self.node.type == "scrcpy":
                self.client.request("POST", "/api/stop", json={"device_id": remote_id})
            else:
                q = urllib.parse.quote(remote_id)
                self.client.request("POST", f"/api/devices/{q}/disconnect", json={})
        with self._lock:
            self._controllers.pop(udid, None)
            state.controllers.pop(udid, None)
        dev = state.get_device(udid)
        if dev:
            dev.connected = False
            dev.streaming = False
            dev.screen_provider = None
        state.forget(udid)

    def check_wda(self, udid: str) -> bool:
        dev = state.get_device(udid)
        return bool(dev and dev.connected)

    def controller(self, udid: str) -> RemoteNodeController:
        dev = state.get_device(udid)
        if not dev:
            raise AppError(ErrorCode.NO_IOS_DEVICE, f"Device {udid} not found")
        remote_id = self._resolve_remote_id(udid)
        with self._lock:
            ctrl = self._controllers.get(udid)
            if ctrl is None:
                ctrl = RemoteNodeController(self, udid, remote_id)
                self._controllers[udid] = ctrl
                state.controllers[udid] = ctrl
            return ctrl

    @staticmethod
    def accessibility(udid: str, feature: str, action: str = "toggle") -> dict:
        raise AppError(ErrorCode.BAD_REQUEST, "Accessibility toggle is not supported on this remote node")

    def make_screen_provider(
        self, udid: str, provider_name: Optional[str] = None, fps: Optional[int] = None
    ) -> RemoteSnapshotProvider:
        shot_fps = int(fps or self.config.get("ANDROID_SCREENSHOT_FPS", 8))
        return RemoteSnapshotProvider(self.client, self._resolve_remote_id(udid), fps=shot_fps)

    def fallback_provider(self, udid: str, fps: Optional[int] = None) -> RemoteSnapshotProvider:
        shot_fps = int(fps or self.config.get("ANDROID_SCREENSHOT_FPS", 8))
        return RemoteSnapshotProvider(self.client, self._resolve_remote_id(udid), fps=shot_fps)

    @staticmethod
    def stop_stream(udid: str) -> None:
        session = state.streams.get(udid)
        if session and hasattr(session, "stop"):
            session.stop()

    def list_apps(self, udid: str, system: bool = False) -> dict:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        if self.node.type == "scrcpy":
            scope = "all" if system else "third_party"
            body = self.client.request("GET", f"/api/device/{q}/apps?scope={scope}")
            pkgs = body.get("packages") or body.get("apps") or []
            apps = [
                p if isinstance(p, dict) else {"bundle_id": str(p), "package": str(p), "name": str(p)}
                for p in pkgs
            ]
            return {"apps": apps}
        body = self.client.request("GET", f"/api/devices/{q}/apps?system={'1' if system else '0'}")
        return dict(body.get("data") or body)

    def install_app(self, udid: str, path: str) -> dict:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        field = "file" if self.node.type == "scrcpy" else "ipa"
        url = f"/api/device/{q}/apps/install" if self.node.type == "scrcpy" else f"/api/devices/{q}/apps/install"
        with open(path, "rb") as fh:
            body = self.client.request("POST", url, files={field: (os.path.basename(path), fh)})
        return {"installed": True, "detail": str(body.get("message") or "installed")}

    def uninstall_app(self, udid: str, bundle_id: str) -> dict:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        if self.node.type == "scrcpy":
            self.client.request("DELETE", f"/api/device/{q}/apps/{urllib.parse.quote(bundle_id)}")
            return {"bundle_id": bundle_id, "uninstalled": True}
        body = self.client.request("POST", f"/api/devices/{q}/apps/uninstall", json={"bundle_id": bundle_id})
        return dict(body.get("data") or {"bundle_id": bundle_id, "uninstalled": True})

    def file_tree(self, udid: str, path: str = ".", app: Optional[str] = None) -> dict:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        if self.node.type == "scrcpy":
            target = "/sdcard" if path in (".", "", "/") else path
            body = self.client.request("GET", f"/api/device/{q}/files?path={urllib.parse.quote(target)}")
            entries = body.get("entries") or body.get("items") or []
            norm = []
            for e in entries:
                norm.append(
                    {
                        "name": e.get("name"),
                        "path": e.get("path"),
                        "isDir": bool(e.get("isDir", e.get("is_dir", False))),
                    }
                )
            return {"path": target, "app": app, "entries": norm}
        body = self.client.request("GET", f"/api/devices/{q}/files/tree?path={urllib.parse.quote(path)}")
        return dict(body.get("data") or body)

    def file_pull_to_temp(self, udid: str, src_path: str, app: Optional[str] = None) -> str:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        url = (
            f"/api/device/{q}/files/pull?path={urllib.parse.quote(src_path)}"
            if self.node.type == "scrcpy"
            else f"/api/devices/{q}/files/pull?path={urllib.parse.quote(src_path)}"
        )
        resp = self.client.request("GET", url, expect_json=False)
        tmp_dir = tempfile.mkdtemp(prefix="nodefile_")
        name = os.path.basename(src_path.rstrip("/")) or "download"
        local = os.path.join(tmp_dir, name)
        with open(local, "wb") as fh:
            fh.write(resp.content)
        return local

    def file_push(self, udid: str, local_path: str, dst_path: str, app: Optional[str] = None) -> dict:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        with open(local_path, "rb") as fh:
            if self.node.type == "scrcpy":
                dst_dir = os.path.dirname(dst_path) or "/sdcard/Download"
                self.client.request(
                    "POST",
                    f"/api/device/{q}/files/push",
                    files={"file": (os.path.basename(dst_path), fh)},
                    data={"dir": dst_dir},
                )
            else:
                self.client.request(
                    "POST",
                    f"/api/devices/{q}/files/push",
                    files={"file": (os.path.basename(local_path), fh)},
                    data={"dst_path": dst_path},
                )
        return {"dst_path": dst_path, "pushed": True}

    def collect_device_info(self, udid: str) -> dict:
        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        if self.node.type == "scrcpy":
            body = self.client.request("GET", f"/api/device/{q}/info")
            info = dict(body.get("info") or {})
            info.setdefault("udid", udid)
            info.setdefault("platform", "android")
            info["node_id"] = self.node.id
            return info
        body = self.client.request("GET", f"/api/devices/{q}/info")
        info = dict((body.get("data") or {}).get("info") or {})
        info["node_id"] = self.node.id
        return info

    def log_popen(self, udid: str, level: str = "I", **_kwargs):
        if self.ssh_adb is not None:
            return self.ssh_adb.logcat_popen(self._resolve_remote_id(udid), level=level)
        raise AppError(
            ErrorCode.BAD_REQUEST,
            f"Live syslog streaming for remote node '{self.node.id}' requires ssh_host or direct node SSE",
        )

    def stream_logs(self, udid: str, level: str = "I"):
        """Yield decoded log lines from remote node SSE (or SSH adb fallback)."""
        if self.ssh_adb is not None:
            proc = self.ssh_adb.logcat_popen(self._resolve_remote_id(udid), level=level)
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    s = line.rstrip("\r\n")
                    if s:
                        yield s
            finally:
                with suppress(Exception):
                    proc.terminate()
            return

        remote_id = self._resolve_remote_id(udid)
        q = urllib.parse.quote(remote_id)
        if self.node.type == "scrcpy":
            path = f"/api/device/{q}/logcat?level={urllib.parse.quote(level)}"
        else:
            path = f"/api/devices/{q}/syslog?level={urllib.parse.quote(level)}"
        headers = {}
        if self.node.token:
            headers["Authorization"] = f"Bearer {self.node.token}"
            headers["X-Node-Token"] = self.node.token

        for attempt in range(2):
            with self.client._client.stream("GET", path, headers=headers, timeout=None) as resp:  # noqa: SLF001
                if resp.status_code == 401 and attempt == 0 and self.node.password:
                    self.client.login()
                    continue
                if resp.status_code >= 400:
                    raise AppError(
                        ErrorCode.BAD_REQUEST,
                        f"Remote log SSE HTTP {resp.status_code} on {path}",
                    )
                for raw_line in resp.iter_lines():
                    if not raw_line or raw_line.startswith(":"):
                        continue
                    if raw_line.startswith("data: "):
                        yield raw_line[6:]
                return

    def shutdown(self) -> None:
        with suppress(Exception):
            self.webrtc.shutdown()
        self.client.close()
