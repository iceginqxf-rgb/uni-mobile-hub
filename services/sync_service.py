"""Cross-OS synchronous group control (one master → N slaves across Android & iOS)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from services.event_bus import emit
from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)
_tls = threading.local()


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, float(val)))


class SyncService:
    """Manage master→slaves groups and concurrently fan out normalized actions."""

    def __init__(self, max_workers: int = 8):
        self._lock = threading.RLock()
        self._groups: Dict[str, List[str]] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sync")

    def get_status(self) -> dict:
        with self._lock:
            return {"groups": {m: list(s) for m, s in self._groups.items()}}

    def get_slaves(self, master: str) -> List[str]:
        with self._lock:
            return list(self._groups.get(master, ()))

    def set_group(self, master: str, slaves: List[str]) -> dict:
        if not master or not state.get_device(master):
            raise AppError(ErrorCode.DEVICE_NOT_FOUND, f"Master device not found: {master}")

        seen = set()
        cleaned: List[str] = []
        for s in slaves or []:
            sid = str(s or "").strip()
            if not sid or sid == master or sid in seen:
                continue
            if not state.get_device(sid):
                raise AppError(ErrorCode.DEVICE_NOT_FOUND, f"Slave device not found: {sid}")
            seen.add(sid)
            cleaned.append(sid)

        with self._lock:
            if cleaned:
                self._groups[master] = cleaned
            else:
                self._groups.pop(master, None)
            snapshot = self.get_status()
        emit("sync_updated", snapshot)
        return snapshot

    def clear_group(self, master: Optional[str] = None) -> dict:
        with self._lock:
            if master:
                self._groups.pop(master, None)
            else:
                self._groups.clear()
            snapshot = self.get_status()
        emit("sync_updated", snapshot)
        return snapshot

    def fanout(self, master: str, action: str, payload: dict) -> List[dict]:
        """Dispatch *action* to every slave configured for *master*.

        Coordinates are normalized (`nx`, `ny`, `nx1`, `ny1`, `nx2`, `ny2` in 0..1)
        so an operation on one OS/resolution lands proportionally on any other.
        Uses a thread-local re-entrancy guard and per-slave exception isolation.
        """
        if getattr(_tls, "in_fanout", False):
            return []
        slaves = self.get_slaves(master)
        if not slaves:
            return []

        futures = [(s, self._pool.submit(self._run_slave, s, action, dict(payload))) for s in slaves]
        results: List[dict] = []
        for sid, fut in futures:
            try:
                results.append(fut.result(timeout=15))
            except Exception as exc:
                _log.warning("sync fanout %s→%s (%s) failed: %s", master[:10], sid[:10], action, exc)
                results.append({"udid": sid, "ok": False, "error": str(exc)})
        return results

    @staticmethod
    def _run_slave(udid: str, action: str, payload: dict) -> dict:
        from services.ios_control_service import ios_control_service

        if not state.get_device(udid):
            return {"udid": udid, "ok": False, "error": "offline"}

        _tls.in_fanout = True
        try:
            if action == "tap":
                ios_control_service.tap(udid, {"nx": _clamp01(payload["nx"]), "ny": _clamp01(payload["ny"])})
            elif action == "double_tap":
                ios_control_service.double_tap(udid, {"nx": _clamp01(payload["nx"]), "ny": _clamp01(payload["ny"])})
            elif action == "long_press":
                ios_control_service.long_press(udid, {
                    "nx": _clamp01(payload["nx"]),
                    "ny": _clamp01(payload["ny"]),
                    "duration": payload.get("duration", 0.8),
                })
            elif action == "swipe":
                ios_control_service.swipe(udid, {
                    "nx1": _clamp01(payload["nx1"]),
                    "ny1": _clamp01(payload["ny1"]),
                    "nx2": _clamp01(payload["nx2"]),
                    "ny2": _clamp01(payload["ny2"]),
                    "duration": payload.get("duration", 0.3),
                })
            elif action == "input_text":
                ios_control_service.input_text(udid, {"text": payload.get("text", "")})
            elif action == "key":
                ios_control_service.key(udid, str(payload.get("name", "")))
            elif action == "button":
                ios_control_service.button(udid, str(payload.get("name", "")))
            else:
                return {"udid": udid, "ok": False, "error": f"unsupported action: {action}"}
            return {"udid": udid, "ok": True}
        except Exception as exc:
            _log.warning("sync slave %s (%s) error: %s", udid[:10], action, exc)
            return {"udid": udid, "ok": False, "error": str(exc)}
        finally:
            _tls.in_fanout = False


sync_service = SyncService()
