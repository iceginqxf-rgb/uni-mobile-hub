"""Subprocess ADB wrapper for local (or SSH-tunneled) Android devices."""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from typing import Dict, List, Optional, Tuple

from utils.app_errors import AppError, ErrorCode
from utils.image_utils import to_jpeg
from utils.logging_setup import get_logger

_log = get_logger(__name__)

_ADBKEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


def _quote_arg(value: str) -> str:
    return shlex.quote(value)


class AdbClient:
    """Thin, thread-safe wrapper around the ``adb`` CLI binary."""

    def __init__(self, adb_bin: str = "", command_timeout: int = 15, ssh_host: str = "") -> None:
        self._explicit_bin = (adb_bin or "").strip()
        self.command_timeout = max(3, int(command_timeout))
        self.ssh_host = (ssh_host or "").strip()
        self._lock = threading.Lock()
        self._meta_cache: Dict[str, dict] = {}

    def resolve_bin(self) -> Optional[str]:
        if self.ssh_host:
            return self._explicit_bin or "adb"
        if self._explicit_bin:
            if os.path.exists(self._explicit_bin) or shutil.which(self._explicit_bin):
                return self._explicit_bin
            return None
        return shutil.which("adb")

    def is_available(self) -> bool:
        return self.resolve_bin() is not None

    def _build_cmd(self, serial: Optional[str], args: List[str]) -> List[str]:
        adb_bin = self.resolve_bin()
        if not adb_bin:
            raise AppError(ErrorCode.BAD_REQUEST, "adb binary not found")
        adb_args = [adb_bin]
        if serial:
            adb_args += ["-s", serial]
        adb_args += args
        if self.ssh_host:
            remote_cmd = " ".join(_quote_arg(a) for a in adb_args)
            return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.ssh_host, remote_cmd]
        return adb_args

    def run(
        self,
        args: List[str],
        serial: Optional[str] = None,
        timeout: Optional[int] = None,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = self._build_cmd(serial, args)
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=text,
                timeout=timeout or self.command_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppError(
                ErrorCode.COMMAND_TIMEOUT,
                f"adb command timed out: {' '.join(args[:3])}",
            ) from exc
        except OSError as exc:
            raise AppError(ErrorCode.INTERNAL_ERROR, f"adb execution failed: {exc}") from exc

    def shell(self, serial: str, shell_cmd: str, timeout: Optional[int] = None) -> str:
        res = self.run(["shell", shell_cmd], serial=serial, timeout=timeout, text=True)
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip()
            raise AppError(ErrorCode.BAD_REQUEST, f"adb shell failed: {err[:200]}")
        return res.stdout or ""

    def list_devices(self) -> List[dict]:
        """Return online ``device`` entries enriched with cached model/os/size."""
        if not self.is_available():
            return []
        res = self.run(["devices", "-l"], timeout=6)
        if res.returncode != 0:
            return []

        devices: List[dict] = []
        seen_online: set[str] = set()
        for line in (res.stdout or "").splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            serial, st = parts[0], parts[1]
            if st != "device":
                continue
            seen_online.add(serial)
            kv = {}
            for tok in parts[2:]:
                if ":" in tok:
                    k, v = tok.split(":", 1)
                    kv[k] = v
            meta = self._read_meta(serial, kv.get("model", ""))
            devices.append(
                {
                    "udid": serial,
                    "name": meta.get("name") or kv.get("model") or serial,
                    "product_type": meta.get("model") or kv.get("model") or "",
                    "os_version": meta.get("os_version") or "",
                    "screen_width": meta.get("width"),
                    "screen_height": meta.get("height"),
                    "has_adbkeyboard": meta.get("has_adbkeyboard", False),
                }
            )
        with self._lock:
            for cached_id in list(self._meta_cache.keys()):
                if cached_id not in seen_online:
                    self._meta_cache.pop(cached_id, None)
        return devices

    def _read_meta(self, serial: str, fallback_model: str = "") -> dict:
        with self._lock:
            cached = self._meta_cache.get(serial)
        if cached is not None:
            return dict(cached)

        script = (
            "getprop ro.product.marketname 2>/dev/null; echo '---';"
            "getprop ro.product.vendor.marketname 2>/dev/null; echo '---';"
            "getprop ro.product.model 2>/dev/null; echo '---';"
            "getprop ro.build.version.release 2>/dev/null; echo '---';"
            "wm size 2>/dev/null; echo '---';"
            "ime list -s 2>/dev/null"
        )
        out = ""
        try:
            out = self.shell(serial, script, timeout=6)
        except AppError:
            out = ""
        sections = [s.strip() for s in out.split("---")]
        while len(sections) < 6:
            sections.append("")
        mkt, vmkt, model, ver, wm_out, imes = sections[:6]
        model = model or fallback_model
        name = mkt or vmkt or model or serial
        w, h = self._parse_wm_size(wm_out)
        meta = {
            "name": name,
            "model": model,
            "os_version": ver,
            "width": w,
            "height": h,
            "has_adbkeyboard": _ADBKEYBOARD_IME in imes,
        }
        with self._lock:
            self._meta_cache[serial] = dict(meta)
        return meta

    @staticmethod
    def _parse_wm_size(raw: str) -> Tuple[Optional[int], Optional[int]]:
        physical: Tuple[Optional[int], Optional[int]] = (None, None)
        override: Tuple[Optional[int], Optional[int]] = (None, None)
        for line in raw.splitlines():
            m = re.search(r"(\d+)\s*x\s*(\d+)", line)
            if not m:
                continue
            dims = (int(m.group(1)), int(m.group(2)))
            if "override" in line.lower():
                override = dims
            elif "physical" in line.lower():
                physical = dims
            else:
                physical = dims
        return override if override[0] else physical

    def get_screen_size(self, serial: str) -> Tuple[int, int]:
        meta = self._read_meta(serial)
        if meta.get("width") and meta.get("height"):
            return int(meta["width"]), int(meta["height"])
        out = self.shell(serial, "wm size", timeout=5)
        w, h = self._parse_wm_size(out)
        if not w or not h:
            raise AppError(ErrorCode.COORDINATE_MAPPING_FAILED, f"Cannot resolve wm size for {serial}")
        with self._lock:
            self._meta_cache.setdefault(serial, {})["width"] = w
            self._meta_cache[serial]["height"] = h
        return w, h

    def get_orientation(self, serial: str) -> str:
        try:
            out = self.shell(serial, "dumpsys input | grep SurfaceOrientation", timeout=4)
            m = re.search(r"SurfaceOrientation:\s*(\d+)", out)
            if m and int(m.group(1)) in (1, 3):
                return "LANDSCAPE"
        except AppError:
            pass
        return "PORTRAIT"

    def tap(self, serial: str, x: int, y: int) -> None:
        self.shell(serial, f"input tap {int(x)} {int(y)}")

    def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, duration_s: float = 0.3) -> None:
        ms = max(50, min(5000, int(round(duration_s * 1000))))
        self.shell(serial, f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {ms}")

    def keyevent(self, serial: str, keycode: int) -> None:
        self.shell(serial, f"input keyevent {int(keycode)}")

    def input_text(self, serial: str, text: str) -> None:
        if not text:
            return
        if text == "\b":
            self.keyevent(serial, 67)
            return
        if text == "\n":
            self.keyevent(serial, 66)
            return
        if text == "\t":
            self.keyevent(serial, 61)
            return
        if text == " ":
            self.keyevent(serial, 62)
            return

        # ASCII single-line strings work natively via `adb shell input text`.
        if all(32 <= ord(ch) < 127 for ch in text) and "\n" not in text:
            escaped = (
                text.replace("\\", "\\\\")
                .replace(" ", "%s")
                .replace("&", "\\&")
                .replace("<", "\\<")
                .replace(">", "\\>")
                .replace("(", "\\(")
                .replace(")", "\\)")
                .replace("|", "\\|")
                .replace(";", "\\;")
                .replace("'", "\\'")
                .replace('"', '\\"')
                .replace("$", "\\$")
            )
            self.shell(serial, f"input text {escaped}")
            return

        meta = self._read_meta(serial)
        if meta.get("has_adbkeyboard"):
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            self.shell(
                serial,
                f"orig=$(settings get secure default_input_method); "
                f"ime set {_ADBKEYBOARD_IME} >/dev/null 2>&1; "
                f"am broadcast -a ADB_INPUT_B64 --es msg '{b64}' >/dev/null 2>&1; "
                f"[ -n \"$orig\" ] && [ \"$orig\" != \"null\" ] && ime set \"$orig\" >/dev/null 2>&1 || true",
            )
            return

        # Fallback for Unicode without ADBKeyBoard: set clipboard + paste keyevent (279).
        self.set_clipboard(serial, text)
        self.keyevent(serial, 279)

    def set_clipboard(self, serial: str, text: str) -> None:
        self.shell(serial, f"cmd clipboard set-text {_quote_arg(text)}")

    def get_clipboard(self, serial: str) -> str:
        try:
            out = self.shell(serial, "cmd clipboard get-text 2>/dev/null || true", timeout=4)
            return out.strip()
        except AppError:
            return ""

    def screenshot_png(self, serial: str) -> bytes:
        res = self.run(["exec-out", "screencap", "-p"], serial=serial, timeout=10, text=False)
        if res.returncode != 0 or not res.stdout:
            raise AppError(ErrorCode.WDA_REQUEST_FAILED, f"adb screencap failed for {serial}")
        return bytes(res.stdout)

    def screenshot_jpeg(self, serial: str, quality: int = 70) -> bytes:
        return to_jpeg(self.screenshot_png(serial), quality=quality)

    def list_apps(self, serial: str, system: bool = False) -> List[dict]:
        args = "pm list packages" if system else "pm list packages -3"
        out = self.shell(serial, args, timeout=10)
        apps = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkg = line[len("package:"):].strip()
                if pkg:
                    apps.append({"bundle_id": pkg, "package": pkg, "name": pkg})
        apps.sort(key=lambda a: a["bundle_id"])
        return apps

    def install_apk(self, serial: str, apk_path: str) -> Tuple[bool, str]:
        res = self.run(["install", "-r", apk_path], serial=serial, timeout=120, text=True)
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        return (res.returncode == 0 and "Success" in out), out

    def uninstall_app(self, serial: str, package: str) -> Tuple[bool, str]:
        res = self.run(["uninstall", package], serial=serial, timeout=30, text=True)
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        return (res.returncode == 0 and "Success" in out), out

    def launch_app(self, serial: str, package: str) -> None:
        self.shell(serial, f"monkey -p {_quote_arg(package)} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1")

    def terminate_app(self, serial: str, package: str) -> None:
        self.shell(serial, f"am force-stop {_quote_arg(package)}")

    def list_dir(self, serial: str, path: str = "/sdcard") -> List[dict]:
        target = path if path and path not in (".", "/") else "/sdcard"
        cmd = (
            f"for f in {_quote_arg(target.rstrip('/'))}/*; do "
            "[ -e \"$f\" ] || continue; "
            "if [ -d \"$f\" ]; then echo \"D|$f\"; else echo \"F|$f\"; fi; "
            "done"
        )
        out = self.shell(serial, cmd, timeout=10)
        entries = []
        for line in out.splitlines():
            if "|" not in line:
                continue
            kind, full = line.split("|", 1)
            entries.append(
                {
                    "name": os.path.basename(full.rstrip("/")) or full,
                    "path": full,
                    "isDir": kind == "D",
                }
            )
        entries.sort(key=lambda e: (not e["isDir"], e["name"].lower()))
        return entries

    def pull_to_temp(self, serial: str, src_path: str) -> str:
        tmp_dir = tempfile.mkdtemp(prefix="adbfile_")
        name = os.path.basename(src_path.rstrip("/")) or "download"
        local = os.path.join(tmp_dir, name)
        res = self.run(["pull", src_path, local], serial=serial, timeout=60, text=True)
        if res.returncode != 0 or not os.path.exists(local):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            err = ((res.stderr or "") + " " + (res.stdout or "")).strip()
            raise AppError(ErrorCode.BAD_REQUEST, f"adb pull failed: {err[:200]}", {"src": src_path})
        return local

    def push_file(self, serial: str, local_path: str, dst_path: str) -> None:
        dst = dst_path if dst_path.startswith("/") else f"/sdcard/Download/{dst_path}"
        res = self.run(["push", local_path, dst], serial=serial, timeout=60, text=True)
        if res.returncode != 0:
            err = ((res.stderr or "") + " " + (res.stdout or "")).strip()
            raise AppError(ErrorCode.BAD_REQUEST, f"adb push failed: {err[:200]}", {"dst": dst})

    def logcat_popen(self, serial: str, level: str = "I") -> subprocess.Popen:
        lvl = (level or "I").strip().upper()[:1] or "I"
        cmd = self._build_cmd(serial, ["logcat", "-v", "time", f"*:{lvl}"])
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )

    def collect_info(self, serial: str) -> dict:
        meta = self._read_meta(serial)
        w, h = self.get_screen_size(serial)
        script = (
            "getprop ro.product.manufacturer 2>/dev/null; echo '---';"
            "getprop ro.product.cpu.abi 2>/dev/null; echo '---';"
            "getprop ro.build.display.id 2>/dev/null; echo '---';"
            "dumpsys battery 2>/dev/null | grep -E 'level:|status:' | head -n 4"
        )
        out = ""
        try:
            out = self.shell(serial, script, timeout=5)
        except AppError:
            out = ""
        parts = [p.strip() for p in out.split("---")]
        while len(parts) < 4:
            parts.append("")
        mfr, abi, build, batt_raw = parts[:4]
        info: dict = {
            "udid": serial,
            "platform": "android",
            "name": meta.get("name") or serial,
            "marketing": meta.get("name") or serial,
            "product_type": meta.get("model") or "",
            "os_version": meta.get("os_version") or "",
            "manufacturer": mfr,
            "cpu_arch": abi,
            "build": build,
            "connection": "ssh-adb" if self.ssh_host else "usb",
            "resolution": {"w": w, "h": h},
            "has_adbkeyboard": bool(meta.get("has_adbkeyboard")),
        }
        lvl_m = re.search(r"level:\s*(\d+)", batt_raw)
        if lvl_m:
            st_m = re.search(r"status:\s*(\d+)", batt_raw)
            info["battery"] = {
                "level": int(lvl_m.group(1)),
                "charging": bool(st_m and int(st_m.group(1)) in (2, 5)),
            }
        return info

    @staticmethod
    def safe_json_dumps(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False)
