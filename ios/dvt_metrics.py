"""In-process iOS 17+ DVT metrics (RAM usage and running applications).

Uses pymobiledevice3's ``UserspaceRsdTunnel`` + ``DvtProvider`` / ``DeviceInfo`` /
``Sysmontap`` so we do not depend on go-ios CLI parsing or spawn subprocesses.
All pymobiledevice3 DVT imports stay lazy so hosts/tests without DVT degrade
cleanly.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from typing import Any, Optional

from utils.logging_setup import get_logger

_log = get_logger(__name__)

_LOCKS_GUARD = threading.Lock()
_UDID_LOCKS: dict[str, threading.Lock] = {}

_MEM_CACHE_TTL = 5.0
_MEM_CACHE: dict[str, tuple[float, dict[str, int]]] = {}

_EXCLUDED_BUNDLE_IDS = {
    "com.apple.springboard",
    "com.apple.spotlight",
    "com.apple.loginwindow",
    "com.apple.purplebuddy",
    "com.apple.setup",
}

_HIDDEN_UI_TOKENS = (
    "uiservice",
    "viewservice",
    "servicesservice",
    "securityalert",
    "voiceassistant",
    "remotealert",
    "systemvoiceassistant",
    "relay",
    "overlay",
    "inputui",
)


def _udid_lock(udid: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _UDID_LOCKS.get(udid)
        if lock is None:
            lock = threading.Lock()
            _UDID_LOCKS[udid] = lock
        return lock


def _run_async(coro):
    """Run an async coroutine safely even if caller already has a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def parse_sysmon_memory(
    system_attrs: list[str],
    system_values: list[Any],
    page_size: int = 16384,
) -> Optional[dict[str, int]]:
    """Compute ``{used, total}`` bytes from a Sysmontap ``System`` sample."""
    if not system_attrs or not system_values:
        return None
    vals = dict(zip(system_attrs, system_values))
    raw_phys = vals.get("physMemSize")
    if isinstance(raw_phys, bool) or not isinstance(raw_phys, (int, float)) or raw_phys <= 0:
        return None

    scale = 1 if raw_phys > 1_000_000_000 else page_size
    total_bytes = int(raw_phys * scale)
    if total_bytes <= 0:
        return None

    if "vmIntPageCount" in vals and "vmWireCount" in vals:
        internal = max(0, int(vals.get("vmIntPageCount") or 0) - int(vals.get("vmPurgeableCount") or 0))
        wired = max(0, int(vals.get("vmWireCount") or 0))
        compressed = max(0, int(vals.get("vmCompressorPageCount") or 0))
        used_val = internal + wired + compressed
    elif "vmActiveCount" in vals:
        used_val = (
            max(0, int(vals.get("vmActiveCount") or 0))
            + max(0, int(vals.get("vmWireCount") or 0))
            + max(0, int(vals.get("vmCompressorPageCount") or 0))
        )
    elif "vmUsedCount" in vals:
        used_val = max(0, int(vals.get("vmUsedCount") or 0))
    else:
        return None

    used_bytes = min(total_bytes, max(0, int(used_val * scale)))
    return {"used": used_bytes, "total": total_bytes}


def collect_memory_info(
    udid: str,
    timeout: float = 4.0,
    use_cache: bool = True,
) -> Optional[dict[str, int]]:
    """Return live RAM ``{used, total}`` in bytes for an iOS 17+ device."""
    now = time.monotonic()
    if use_cache:
        cached = _MEM_CACHE.get(udid)
        if cached and (now - cached[0]) < _MEM_CACHE_TTL:
            return dict(cached[1])

    async def _fetch() -> Optional[dict[str, int]]:
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.device_info import DeviceInfo
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap

        async with asyncio.timeout(timeout):
            async with UserspaceRsdTunnel(serial=udid, autopair=False) as rsd:
                async with DvtProvider(rsd) as dvt:
                    async with DeviceInfo(dvt) as di:
                        sys_attrs = list(await di.sysmon_system_attributes())
                    # Sysmontap requires a non-empty process attribute list to yield samples.
                    sysmon = Sysmontap(dvt, ["pid"], sys_attrs, interval_ms=500)
                    async with sysmon:
                        for _ in range(10):
                            raw = await sysmon.channel.receive_plist()
                            items = raw if isinstance(raw, list) else [raw]
                            for item in items:
                                if isinstance(item, dict) and "System" in item:
                                    return parse_sysmon_memory(sys_attrs, item["System"])
        return None

    with _udid_lock(udid):
        if use_cache:
            cached = _MEM_CACHE.get(udid)
            if cached and (time.monotonic() - cached[0]) < _MEM_CACHE_TTL:
                return dict(cached[1])
        try:
            mem = _run_async(_fetch())
        except Exception as exc:
            _log.debug("collect_memory_info failed for %s: %s", udid[:12], exc)
            return None
        if mem and mem.get("total", 0) > 0:
            _MEM_CACHE[udid] = (time.monotonic(), dict(mem))
            return dict(mem)
        return None


def filter_running_apps(
    procs: list[dict[str, Any]],
    foreground_bundle_id: str = "",
    include_system: bool = False,
) -> list[dict[str, Any]]:
    """Filter, deduplicate, and sort raw DVT ``proclist`` entries into switchable apps."""
    by_bundle: dict[str, tuple[float, dict[str, Any]]] = {}

    for p in procs or []:
        if p.get("isApplication") is not True:
            continue
        bundle_id = str(p.get("bundleIdentifier") or "").strip()
        if not bundle_id:
            continue

        proc_name = str(p.get("name") or "")
        low_bid = bundle_id.lower()
        low_name = proc_name.lower()

        if "webdriveragent" in low_bid or "webdriveragent" in low_name:
            continue
        if low_bid in _EXCLUDED_BUNDLE_IDS:
            continue

        real_app_name = str(p.get("realAppName") or "")
        if not include_system:
            if (
                real_app_name.startswith("/System/Library/CoreServices/")
                or "/PlugIns/" in real_app_name
                or ".appex" in real_app_name
            ):
                continue
            if any(tok in low_bid or tok in low_name for tok in _HIDDEN_UI_TOKENS):
                continue

        pid = int(p.get("pid") or 0)
        sd = p.get("startDate")
        start_date = sd.isoformat() if hasattr(sd, "isoformat") else str(sd or "")
        try:
            start_ts = float(sd.timestamp()) if hasattr(sd, "timestamp") else float(pid)
        except Exception:
            start_ts = float(pid)

        entry = {
            "bundle_id": bundle_id,
            "name": str(p.get("displayLocalizedAppName") or proc_name or bundle_id),
            "pid": pid,
            "foreground": bool(foreground_bundle_id and bundle_id == foreground_bundle_id),
            "is_user_app": "/Bundle/Application/" in real_app_name,
            "start_date": start_date,
        }

        prev = by_bundle.get(bundle_id)
        if prev is None or pid > prev[1]["pid"]:
            by_bundle[bundle_id] = (start_ts, entry)

    items = list(by_bundle.values())
    items.sort(
        key=lambda pair: (
            0 if pair[1]["foreground"] else 1,
            0 if pair[1]["is_user_app"] else 1,
            -pair[0],
            pair[1]["name"].lower(),
        )
    )
    return [pair[1] for pair in items]


def list_running_apps(
    udid: str,
    foreground_bundle_id: str = "",
    include_system: bool = False,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Return running switchable applications on an iOS 17+ device via DVT proclist."""

    async def _fetch() -> list[dict[str, Any]]:
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.device_info import DeviceInfo
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider

        async with asyncio.timeout(timeout):
            async with UserspaceRsdTunnel(serial=udid, autopair=False) as rsd:
                async with DvtProvider(rsd) as dvt:
                    async with DeviceInfo(dvt) as di:
                        return list(await di.proclist())

    with _udid_lock(udid):
        try:
            procs = _run_async(_fetch())
        except Exception as exc:
            _log.debug("list_running_apps failed for %s: %s", udid[:12], exc)
            return []
    return filter_running_apps(
        procs,
        foreground_bundle_id=foreground_bundle_id,
        include_system=include_system,
    )
