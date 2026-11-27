"""Node health & streaming telemetry REST API (/api/nodes)."""

from __future__ import annotations

from contextlib import suppress
import time

from flask import Blueprint

from api import api
from nodes.remote_node_adapter import RemoteNodeAdapter
from nodes.scrcpy_webrtc_relay import scrcpy_webrtc_relay
from services import get_adapter
from services.ios_stream_service import IOSStreamService
from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode

bp = Blueprint("nodes", __name__, url_prefix="/api/nodes")


def _local_adapter_entry(adapter) -> dict:
    sid = getattr(adapter, "source_id", getattr(adapter, "platform", "local"))
    devs = [d for d in state.list_devices() if getattr(d, "source", None) == sid]
    avail = False
    with suppress(Exception):
        avail = bool(adapter.is_backend_available())
    return {
        "id": sid,
        "type": getattr(adapter, "platform", "local"),
        "url": "local",
        "online": avail,
        "latency_ms": 0.0 if avail else None,
        "last_ok_at": None,
        "last_error": "",
        "consecutive_failures": 0,
        "retry_in_sec": 0.0,
        "reconnectable": False,
        "device_count": len(devs),
        "source_id": sid,
    }


@bp.get("")
@api
def list_nodes():
    registry = get_adapter()
    nodes = []
    adapters = registry.adapters() if hasattr(registry, "adapters") else [registry]
    for adapter in adapters:
        if isinstance(adapter, RemoteNodeAdapter):
            nodes.append(adapter.node_status())
        else:
            nodes.append(_local_adapter_entry(adapter))

    stream_svc = IOSStreamService(getattr(registry, "config", {}))
    relay_counts = scrcpy_webrtc_relay.active_udids()
    streams = []
    for d in state.list_devices():
        st = stream_svc.get_status(d.udid)
        streaming = bool(st.get("running"))
        provider = st.get("provider")
        viewers = int(st.get("subscribers") or 0)
        if not streaming and relay_counts.get(d.udid, 0) > 0:
            streaming = True
            provider = "scrcpy-webrtc"
            viewers = relay_counts[d.udid]
        streams.append({
            "udid": d.udid,
            "name": d.name,
            "platform": d.platform,
            "node_id": d.node_id,
            "connected": bool(d.connected),
            "streaming": streaming,
            "provider": provider,
            "fps": st.get("fps", 0.0),
            "viewers": viewers,
        })
    return {"nodes": nodes, "streams": streams, "server_time": time.time()}


@bp.post("/<node_id>/reconnect")
@api
def reconnect_node(node_id: str):
    registry = get_adapter()
    adapters = registry.adapters() if hasattr(registry, "adapters") else [registry]
    for adapter in adapters:
        if isinstance(adapter, RemoteNodeAdapter) and adapter.node.id == node_id:
            return {"node": adapter.force_reconnect()}
    raise AppError(ErrorCode.NOT_FOUND, f"Remote node '{node_id}' not found")
