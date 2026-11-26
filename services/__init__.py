"""Service layer + the multi-platform adapter registry accessor.

``init_platform(config)`` is called once at app startup; services then call
``get_adapter()`` for aggregate operations or ``get_adapter(udid)`` to obtain
the specific platform/node adapter owning ``udid``.
"""

from __future__ import annotations

from typing import Optional

_registry = None


def init_platform(config: dict):
    global _registry
    from services.adapter_registry import AdapterRegistry

    registry = AdapterRegistry(config)
    if str(config.get("IOS_ENABLED", "1")) == "1":
        from ios.ios_adapter import IOSAdapter  # lazy

        registry.register(IOSAdapter(config), "ios")
    if str(config.get("ANDROID_ENABLED", "0")) == "1":
        from android.android_adapter import AndroidAdapter  # lazy

        registry.register(AndroidAdapter(config), "android")
    if config.get("REMOTE_NODES"):
        from nodes.node_config import parse_remote_nodes
        from nodes.remote_node_adapter import RemoteNodeAdapter

        for node_cfg in parse_remote_nodes(config.get("REMOTE_NODES")):
            registry.register(RemoteNodeAdapter(config, node_cfg), f"node:{node_cfg.id}")

    _registry = registry
    return _registry


def get_adapter(udid: Optional[str] = None):
    if _registry is None:
        raise RuntimeError("Platform adapter not initialized — call init_platform first")
    if udid is None:
        return _registry
    return _registry.adapter_for(udid)
