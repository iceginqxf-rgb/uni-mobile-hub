"""Unified cross-platform device model.

Shared by iOS, local Android, and remote Worker node adapters so every HTTP/WS
endpoint, runtime state cache, and frontend view consumes one consistent shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MobileDevice:
    platform: str = "ios"
    udid: str = ""
    name: str = ""
    product_type: str = ""           # e.g. iPhone14,5 or 24094RAD4C
    ios_version: str = ""            # kept for existing iOS UI/test compatibility
    connected: bool = False
    developer_mode: str = "unknown"  # "on" | "off" | "unknown"
    trusted: bool = False
    wda_running: bool = False
    local_wda_port: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    orientation: str = "PORTRAIT"
    streaming: bool = False
    screen_provider: Optional[str] = None
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    os_version: str = ""
    node_id: str = "local"
    source: str = "ios"
    capabilities: List[str] = field(default_factory=list)
    stream_endpoint: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not self.os_version and self.ios_version:
            self.os_version = self.ios_version
        elif self.platform == "ios" and self.os_version and not self.ios_version:
            self.ios_version = self.os_version

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("os_version"):
            d["os_version"] = self.ios_version
        if self.platform == "ios":
            from ios.device_marketing import marketing_name

            d["marketing"] = marketing_name(self.product_type) if self.product_type else ""
        else:
            d["marketing"] = self.name or self.product_type or self.udid
        return d

    def merge(self, other: "MobileDevice") -> None:
        """Update mutable scanned fields while preserving runtime state."""
        self.name = other.name or self.name
        self.product_type = other.product_type or self.product_type
        self.ios_version = other.ios_version or self.ios_version
        self.os_version = other.os_version or self.os_version or self.ios_version
        self.node_id = other.node_id or self.node_id
        self.source = other.source or self.source
        if other.capabilities:
            self.capabilities = list(other.capabilities)
        if other.stream_endpoint is not None:
            self.stream_endpoint = dict(other.stream_endpoint)
        if other.developer_mode != "unknown":
            self.developer_mode = other.developer_mode
        self.trusted = other.trusted or self.trusted
        if other.screen_width:
            self.screen_width = other.screen_width
        if other.screen_height:
            self.screen_height = other.screen_height
        self.last_seen = other.last_seen
