"""Hub-side Socket.IO proxy relaying browser WebRTC signaling to remote Scrcpy workers.

Allows the browser to speak same-origin Socket.IO only to the Hub, avoiding
cross-origin cookie / ``SameSite`` / CORS rejections when signaling a remote
``WebAppFlaskscrcpy`` node while still keeping direct media (or TURN/host ICE)
flowing between the browser PeerConnection and the Worker.
"""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from typing import Any, Callable, Dict, Optional, Tuple

import requests
import socketio as py_socketio

from nodes.remote_node_adapter import RemoteNodeAdapter
from services import get_adapter
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)

EmitFn = Callable[[str, dict], None]
ClientFactory = Callable[[requests.Session], Any]


def _default_client_factory(http_session: requests.Session) -> Any:
    return py_socketio.Client(http_session=http_session, reconnection=False, logger=False, engineio_logger=False)


class ScrcpyWebRTCRelay:
    """Manage upstream python-socketio client sessions keyed by ``(sid, udid)``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[Tuple[str, str], dict] = {}

    def _is_active(self, key: Tuple[str, str], sio: Any) -> bool:
        with self._lock:
            entry = self._sessions.get(key)
            return bool(entry and entry.get("sio") is sio)

    def _drop_if_same(self, key: Tuple[str, str], sio: Any) -> None:
        with self._lock:
            entry = self._sessions.get(key)
            if entry and entry.get("sio") is sio:
                self._sessions.pop(key, None)

    def start_offer(
        self,
        sid: str,
        udid: str,
        sdp: str,
        emit_fn: EmitFn,
        *,
        offer_id: Optional[str] = None,
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        if not sdp:
            raise AppError(ErrorCode.BAD_REQUEST, "Missing WebRTC SDP offer")

        adapter = get_adapter(udid)
        if not isinstance(adapter, RemoteNodeAdapter) or adapter.node.type != "scrcpy":
            raise AppError(
                ErrorCode.BAD_REQUEST,
                f"Device '{udid}' does not belong to a remote Scrcpy worker",
            )

        remote_id = adapter._resolve_remote_id(udid)
        if not adapter.client._client.cookies:
            adapter.client.login()

        with suppress(AppError):
            adapter.client.request("POST", "/api/reservations", json={"device_id": remote_id})
        with suppress(AppError):
            adapter.client.request("POST", "/api/start", json={"device_id": remote_id})

        cookie_header = "; ".join(f"{k}={v}" for k, v in adapter.client._client.cookies.items())
        headers: Dict[str, str] = {"Origin": adapter.node.url}
        if cookie_header:
            headers["Cookie"] = cookie_header
        if adapter.node.token:
            headers["Authorization"] = f"Bearer {adapter.node.token}"
            headers["X-Node-Token"] = adapter.node.token

        sess = requests.Session()
        sess.trust_env = False
        sio = (client_factory or _default_client_factory)(sess)

        self.close(sid, udid)
        key = (sid, udid)
        retried_unavailable = False

        def _with_offer_id(payload: dict) -> dict:
            if offer_id is not None:
                payload["offer_id"] = offer_id
            return payload

        @sio.on("webrtc:answer")
        def _on_answer(data: Any) -> None:
            if not self._is_active(key, sio):
                return
            d = data or {}
            if d.get("device_id") and d.get("device_id") != remote_id:
                return
            emit_fn(
                "scrcpy:webrtc:answer",
                _with_offer_id(
                    {"udid": udid, "sdp": d.get("sdp", ""), "type": d.get("type", "answer")}
                ),
            )

        @sio.on("webrtc:ice")
        def _on_ice(data: Any) -> None:
            if not self._is_active(key, sio):
                return
            d = data or {}
            if d.get("device_id") and d.get("device_id") != remote_id:
                return
            emit_fn(
                "scrcpy:webrtc:ice",
                _with_offer_id(
                    {
                        "udid": udid,
                        "candidate": d.get("candidate"),
                        "sdpMid": d.get("sdpMid"),
                        "sdpMLineIndex": d.get("sdpMLineIndex"),
                    }
                ),
            )

        @sio.on("webrtc:closed")
        def _on_closed(data: Any) -> None:
            nonlocal retried_unavailable
            if not self._is_active(key, sio):
                return
            d = data or {}
            if d.get("device_id") and d.get("device_id") != remote_id:
                return
            reason = str(d.get("reason") or "closed")
            if reason == "device_unavailable" and not retried_unavailable:
                retried_unavailable = True
                with suppress(AppError):
                    adapter.client.request("POST", "/api/start", json={"device_id": remote_id})
                time.sleep(0.6)
                if self._is_active(key, sio):
                    with suppress(Exception):
                        sio.emit("webrtc:offer", {"device_id": remote_id, "sdp": sdp})
                        return
            self._drop_if_same(key, sio)
            emit_fn("scrcpy:webrtc:closed", _with_offer_id({"udid": udid, "reason": reason}))

        try:
            sio.connect(adapter.node.url, transports=["polling"], headers=headers, wait_timeout=6)
        except Exception as exc:
            with suppress(Exception):
                sio.disconnect()
            with suppress(Exception):
                sess.close()
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"Upstream Scrcpy WebRTC connect failed ({adapter.node.id}): {exc}",
            ) from exc

        with self._lock:
            self._sessions[key] = {
                "sio": sio,
                "http_session": sess,
                "remote_id": remote_id,
                "udid": udid,
                "offer_id": offer_id,
            }

        sio.emit("webrtc:offer", {"device_id": remote_id, "sdp": sdp})

    def send_ice(
        self,
        sid: str,
        udid: str,
        candidate: str,
        sdp_mid: Optional[str] = None,
        sdp_mline_index: Optional[int] = None,
    ) -> bool:
        with self._lock:
            entry = self._sessions.get((sid, udid))
        if not entry or not candidate:
            return False
        with suppress(Exception):
            entry["sio"].emit(
                "webrtc:ice",
                {
                    "device_id": entry["remote_id"],
                    "candidate": candidate,
                    "sdpMid": sdp_mid,
                    "sdpMLineIndex": sdp_mline_index,
                },
            )
            return True
        return False

    def active_udids(self) -> Dict[str, int]:
        """Count active relayed WebRTC viewer sessions keyed by device UDID."""
        counts: Dict[str, int] = {}
        with self._lock:
            for _sid, udid in self._sessions:
                counts[udid] = counts.get(udid, 0) + 1
        return counts

    def _drop_entry(self, key: Tuple[str, str]) -> Optional[dict]:
        with self._lock:
            return self._sessions.pop(key, None)

    def close(self, sid: str, udid: str) -> None:
        entry = self._drop_entry((sid, udid))
        if not entry:
            return
        self._teardown(entry)

    def close_sid(self, sid: str) -> None:
        with self._lock:
            keys = [k for k in self._sessions if k[0] == sid]
            entries = [self._sessions.pop(k) for k in keys]
        for entry in entries:
            self._teardown(entry)

    @staticmethod
    def _teardown(entry: dict) -> None:
        with suppress(Exception):
            entry["sio"].emit("webrtc:close", {"device_id": entry["remote_id"]})
        with suppress(Exception):
            entry["sio"].disconnect()
        with suppress(Exception):
            entry["http_session"].close()


scrcpy_webrtc_relay = ScrcpyWebRTCRelay()
