"""Configuration parser for Hub + Worker remote nodes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List

from utils.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class RemoteNodeConfig:
    id: str
    url: str
    type: str = "uni"        # "uni" (uni-mobile-hub Worker) | "scrcpy" (WebAppFlaskscrcpy)
    public_url: str = ""
    username: str = "admin"
    password: str = ""
    token: str = ""
    ssh_host: str = ""
    adb_bin: str = ""
    timeout: float = 15.0

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.url = str(self.url).strip().rstrip("/")
        self.public_url = (str(self.public_url).strip().rstrip("/")) or self.url
        kind = str(self.type or "uni").strip().lower()
        self.type = kind if kind in ("uni", "scrcpy") else "uni"
        self.timeout = max(2.0, float(self.timeout or 15.0))


def parse_remote_nodes(raw: Any) -> List[RemoteNodeConfig]:
    """Parse ``REMOTE_NODES`` from JSON string or list of dicts."""
    if not raw:
        return []
    data = raw
    if isinstance(raw, str):
        raw_str = raw.strip()
        if not raw_str:
            return []
        try:
            data = json.loads(raw_str)
        except json.JSONDecodeError as exc:
            _log.warning("invalid REMOTE_NODES JSON (%s); ignoring remote nodes", exc)
            return []
    if not isinstance(data, list):
        _log.warning("REMOTE_NODES must be a JSON array")
        return []
    nodes: List[RemoteNodeConfig] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not nid or not url or nid in seen:
            continue
        seen.add(nid)
        nodes.append(
            RemoteNodeConfig(
                id=nid,
                url=url,
                type=str(item.get("type") or "uni"),
                public_url=str(item.get("public_url") or ""),
                username=str(item.get("username") or "admin"),
                password=str(item.get("password") or ""),
                token=str(item.get("token") or ""),
                ssh_host=str(item.get("ssh_host") or ""),
                adb_bin=str(item.get("adb_bin") or ""),
                timeout=float(item.get("timeout") or 15.0),
            )
        )
    return nodes
