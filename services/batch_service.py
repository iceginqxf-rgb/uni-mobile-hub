"""Multi-device batch orchestration: parallel/serial APK/IPA install & Agent workflows."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from services.ios_app_service import IOSAppService
from services.ios_control_service import ios_control_service
from services.replay_service import _clamp, validate_steps as _validate_base_steps
from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)

_MAX_JOBS = 30
_MAX_LOGS = 500
_VALID_MODES = {"parallel", "serial"}
_VALID_EXTS = {".apk", ".ipa"}

InstallerFn = Callable[[str, str], dict]
WorkflowRunnerFn = Callable[[str, dict], Any]


def _normalize_targets(targets: Any) -> List[str]:
    if not isinstance(targets, list):
        raise AppError(ErrorCode.BAD_REQUEST, "Field 'targets' must be a list of device UDIDs")
    clean: List[str] = []
    seen = set()
    for t in targets:
        u = str(t or "").strip()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)
    if not clean:
        raise AppError(ErrorCode.BAD_REQUEST, "At least one target device is required")
    return clean


def validate_workflow_steps(raw_steps: Any) -> List[dict]:
    """Validate batch workflow steps (base replay steps + open_app / close_app / screenshot)."""
    if not isinstance(raw_steps, list) or not raw_steps:
        raise AppError(ErrorCode.BAD_REQUEST, "Field 'steps' must be a non-empty list")
    if len(raw_steps) > 500:
        raise AppError(ErrorCode.BAD_REQUEST, "Too many steps (max 500)")

    out: List[dict] = []
    for idx, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} must be an object")
        stype = str(raw.get("type") or "").strip().lower()
        delay_ms = int(round(_clamp(raw.get("delay_ms", 0), 0.0, 60000.0, "delay_ms")))

        if stype in ("open_app", "close_app"):
            app_id = str(raw.get("app") or raw.get("bundle_id") or raw.get("package") or "").strip()
            if not app_id:
                raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} ({stype}) requires app/bundle_id")
            out.append({"type": stype, "app": app_id, "delay_ms": delay_ms})
        elif stype == "screenshot":
            out.append({"type": "screenshot", "delay_ms": delay_ms})
        else:
            step = _validate_base_steps([raw])[0]
            if stype == "text" and raw.get("enter"):
                step["enter"] = True
            out.append(step)
    return out


def _default_workflow_runner(udid: str, step: dict) -> str:
    state.touch(udid)
    stype = step["type"]
    if stype == "tap":
        ios_control_service.tap(udid, {"nx": step["nx"], "ny": step["ny"]}, skip_sync=True)
        return f"tap ({step['nx']}, {step['ny']})"
    if stype == "doubletap":
        ios_control_service.double_tap(udid, {"nx": step["nx"], "ny": step["ny"]}, skip_sync=True)
        return f"doubletap ({step['nx']}, {step['ny']})"
    if stype == "longpress":
        ios_control_service.long_press(
            udid, {"nx": step["nx"], "ny": step["ny"], "duration": step["duration"]}, skip_sync=True
        )
        return f"longpress ({step['nx']}, {step['ny']})"
    if stype == "swipe":
        ios_control_service.swipe(
            udid,
            {
                "nx1": step["nx1"],
                "ny1": step["ny1"],
                "nx2": step["nx2"],
                "ny2": step["ny2"],
                "duration": step["duration"],
            },
            skip_sync=True,
        )
        return "swipe"
    if stype == "button":
        ios_control_service.button(udid, step["name"], skip_sync=True)
        return f"button:{step['name']}"
    if stype == "key":
        ios_control_service.key(udid, step["name"], skip_sync=True)
        return f"key:{step['name']}"
    if stype == "text":
        ios_control_service.input_text(udid, {"text": step["text"]}, skip_sync=True)
        if step.get("enter"):
            ios_control_service.key(udid, "enter", skip_sync=True)
        return f"text({len(step['text'])})"
    if stype == "open_app":
        ios_control_service.launch_app(udid, step["app"])
        return f"open_app:{step['app']}"
    if stype == "close_app":
        ios_control_service.terminate_app(udid, step["app"])
        return f"close_app:{step['app']}"
    if stype == "screenshot":
        ios_control_service.screenshot(udid, as_base64=False)
        return "screenshot"
    return stype


class BatchService:
    """Thread-safe batch installer & workflow executor with progress and logs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, dict] = {}
        self._order: List[str] = []

    @staticmethod
    def _public_job(entry: dict) -> dict:
        return {
            "id": entry["id"],
            "kind": entry["kind"],
            "name": entry["name"],
            "mode": entry["mode"],
            "retries": entry["retries"],
            "status": entry["status"],
            "targets": list(entry["targets"]),
            "total_targets": len(entry["targets"]),
            "completed_targets": sum(
                1 for d in entry["per_device"].values() if d["status"] in ("ok", "failed", "stopped")
            ),
            "ok_targets": sum(1 for d in entry["per_device"].values() if d["status"] == "ok"),
            "failed_targets": sum(1 for d in entry["per_device"].values() if d["status"] == "failed"),
            "progress_pct": entry["progress_pct"],
            "meta": dict(entry["meta"]),
            "per_device": {u: dict(v) for u, v in entry["per_device"].items()},
            "logs": [dict(x) for x in entry["logs"]],
            "started_at": entry["started_at"],
            "finished_at": entry["finished_at"],
        }

    def _register_job(self, entry: dict) -> dict:
        with self._lock:
            self._jobs[entry["id"]] = entry
            self._order.append(entry["id"])
            while len(self._order) > _MAX_JOBS:
                old_id = self._order.pop(0)
                if old_id != entry["id"]:
                    self._jobs.pop(old_id, None)
            return self._public_job(entry)

    def _append_log(self, entry: dict, udid: str, level: str, message: str) -> None:
        with self._lock:
            entry["logs"].append({
                "ts": time.time(),
                "udid": udid,
                "level": level,
                "message": str(message)[:400],
            })
            if len(entry["logs"]) > _MAX_LOGS:
                entry["logs"] = entry["logs"][-_MAX_LOGS:]

    def _recompute_progress(self, entry: dict) -> None:
        with self._lock:
            devs = list(entry["per_device"].values())
            if not devs:
                entry["progress_pct"] = 0
                return
            frac = 0.0
            for d in devs:
                tot = max(1, int(d["total_steps"]))
                if d["status"] in ("ok", "failed", "stopped"):
                    frac += 1.0
                else:
                    frac += min(0.95, float(d["ok_steps"]) / tot)
            entry["progress_pct"] = min(100, int(round((frac / len(devs)) * 100)))

    def _finalize_job(self, entry: dict) -> None:
        with self._lock:
            cancel: threading.Event = entry["_cancel"]
            statuses = [d["status"] for d in entry["per_device"].values()]
            if cancel.is_set() or entry["status"] == "stopped":
                entry["status"] = "stopped"
            elif all(s == "ok" for s in statuses):
                entry["status"] = "completed"
                entry["progress_pct"] = 100
            elif any(s == "ok" for s in statuses):
                entry["status"] = "partial"
                entry["progress_pct"] = 100
            else:
                entry["status"] = "failed"
                entry["progress_pct"] = 100
            if entry["finished_at"] is None:
                entry["finished_at"] = time.time()

    def start_install(
        self,
        targets: Any,
        package_path: str,
        filename: str,
        *,
        mode: str = "parallel",
        retries: Any = 0,
        name: str = "",
        cleanup_path: bool = True,
        installer: Optional[InstallerFn] = None,
    ) -> dict:
        clean_targets = _normalize_targets(targets)
        mode_val = str(mode or "parallel").strip().lower()
        if mode_val not in _VALID_MODES:
            raise AppError(ErrorCode.BAD_REQUEST, f"Invalid mode '{mode}' (expected parallel/serial)")
        retries_val = int(round(_clamp(retries if retries is not None else 0, 0.0, 3.0, "retries")))

        ext = os.path.splitext(filename or package_path)[1].lower()
        if ext not in _VALID_EXTS:
            raise AppError(ErrorCode.BAD_REQUEST, f"Unsupported package type '{ext}' (expected .apk or .ipa)")
        expected_platform = "android" if ext == ".apk" else "ios"

        job_id = uuid.uuid4().hex[:12]
        entry = {
            "id": job_id,
            "kind": "install",
            "name": str(name or "").strip() or f"Install {os.path.basename(filename or package_path)}",
            "mode": mode_val,
            "retries": retries_val,
            "status": "running",
            "targets": clean_targets,
            "progress_pct": 0,
            "meta": {"filename": os.path.basename(filename or package_path), "ext": ext},
            "per_device": {
                u: {
                    "status": "pending",
                    "attempts": 0,
                    "ok_steps": 0,
                    "total_steps": 1,
                    "duration_ms": 0,
                    "detail": "",
                    "error": "",
                }
                for u in clean_targets
            },
            "logs": [],
            "started_at": time.time(),
            "finished_at": None,
            "_cancel": threading.Event(),
        }
        snapshot = self._register_job(entry)
        self._append_log(
            entry,
            "hub",
            "info",
            f"Batch install started: {entry['meta']['filename']} -> {len(clean_targets)} device(s) ({mode_val}, retries={retries_val})",
        )

        install_fn = installer or IOSAppService.install
        t = threading.Thread(
            target=self._run_install_worker,
            args=(entry, package_path, expected_platform, cleanup_path, install_fn),
            name=f"batch-install-{job_id}",
            daemon=True,
        )
        t.start()
        return snapshot

    def _install_one(
        self,
        entry: dict,
        udid: str,
        package_path: str,
        expected_platform: str,
        install_fn: InstallerFn,
    ) -> None:
        cancel: threading.Event = entry["_cancel"]
        if cancel.is_set():
            with self._lock:
                entry["per_device"][udid]["status"] = "stopped"
            return

        t0 = time.monotonic()
        with self._lock:
            entry["per_device"][udid]["status"] = "running"

        dev = state.get_device(udid)
        if dev is not None and dev.platform and dev.platform != expected_platform:
            msg = f"Platform mismatch: cannot install {expected_platform} package onto {dev.platform} device"
            with self._lock:
                d = entry["per_device"][udid]
                d["status"] = "failed"
                d["error"] = msg
                d["duration_ms"] = int(round((time.monotonic() - t0) * 1000))
            self._append_log(entry, udid, "error", msg)
            self._recompute_progress(entry)
            return

        max_attempts = 1 + int(entry["retries"])
        last_err = ""
        for attempt in range(1, max_attempts + 1):
            if cancel.is_set():
                with self._lock:
                    entry["per_device"][udid]["status"] = "stopped"
                self._recompute_progress(entry)
                return
            with self._lock:
                entry["per_device"][udid]["attempts"] = attempt
            self._append_log(entry, udid, "info", f"Installing attempt {attempt}/{max_attempts}...")
            try:
                res = install_fn(udid, package_path) or {}
                detail = str(res.get("detail") or res.get("message") or "installed")[:160]
                with self._lock:
                    d = entry["per_device"][udid]
                    d["status"] = "ok"
                    d["ok_steps"] = 1
                    d["detail"] = detail
                    d["error"] = ""
                    d["duration_ms"] = int(round((time.monotonic() - t0) * 1000))
                self._append_log(entry, udid, "info", f"Install succeeded ({detail})")
                self._recompute_progress(entry)
                return
            except Exception as exc:  # noqa: BLE001 — capture per-device install failure
                last_err = str(exc)[:260]
                self._append_log(entry, udid, "warn" if attempt < max_attempts else "error", f"Attempt {attempt} failed: {last_err}")
                if attempt < max_attempts and cancel.wait(0.8):
                    with self._lock:
                        entry["per_device"][udid]["status"] = "stopped"
                    self._recompute_progress(entry)
                    return

        with self._lock:
            d = entry["per_device"][udid]
            d["status"] = "failed"
            d["error"] = last_err or "Install failed"
            d["duration_ms"] = int(round((time.monotonic() - t0) * 1000))
        self._recompute_progress(entry)

    def _run_install_worker(
        self,
        entry: dict,
        package_path: str,
        expected_platform: str,
        cleanup_path: bool,
        install_fn: InstallerFn,
    ) -> None:
        try:
            targets: List[str] = entry["targets"]
            if entry["mode"] == "serial" or len(targets) == 1:
                for u in targets:
                    if entry["_cancel"].is_set():
                        with self._lock:
                            entry["per_device"][u]["status"] = "stopped"
                        continue
                    self._install_one(entry, u, package_path, expected_platform, install_fn)
            else:
                with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
                    futs = [
                        pool.submit(self._install_one, entry, u, package_path, expected_platform, install_fn)
                        for u in targets
                    ]
                    for f in futs:
                        with suppress(Exception):
                            f.result()
        finally:
            self._finalize_job(entry)
            if cleanup_path and package_path:
                with suppress(OSError):
                    os.remove(package_path)

    def start_workflow(
        self,
        targets: Any,
        raw_steps: Any,
        *,
        mode: str = "parallel",
        retries: Any = 0,
        name: str = "",
        runner: Optional[WorkflowRunnerFn] = None,
    ) -> dict:
        clean_targets = _normalize_targets(targets)
        mode_val = str(mode or "parallel").strip().lower()
        if mode_val not in _VALID_MODES:
            raise AppError(ErrorCode.BAD_REQUEST, f"Invalid mode '{mode}' (expected parallel/serial)")
        retries_val = int(round(_clamp(retries if retries is not None else 0, 0.0, 3.0, "retries")))
        steps = validate_workflow_steps(raw_steps)

        job_id = uuid.uuid4().hex[:12]
        entry = {
            "id": job_id,
            "kind": "workflow",
            "name": str(name or "").strip() or f"Workflow ({len(steps)} steps)",
            "mode": mode_val,
            "retries": retries_val,
            "status": "running",
            "targets": clean_targets,
            "progress_pct": 0,
            "meta": {"step_count": len(steps)},
            "per_device": {
                u: {
                    "status": "pending",
                    "attempts": 0,
                    "ok_steps": 0,
                    "total_steps": len(steps),
                    "duration_ms": 0,
                    "detail": "",
                    "error": "",
                }
                for u in clean_targets
            },
            "logs": [],
            "started_at": time.time(),
            "finished_at": None,
            "_cancel": threading.Event(),
        }
        snapshot = self._register_job(entry)
        self._append_log(
            entry,
            "hub",
            "info",
            f"Batch workflow started: {len(steps)} steps on {len(clean_targets)} device(s) ({mode_val}, retries={retries_val})",
        )

        step_fn = runner or _default_workflow_runner
        t = threading.Thread(
            target=self._run_workflow_worker,
            args=(entry, steps, step_fn),
            name=f"batch-wf-{job_id}",
            daemon=True,
        )
        t.start()
        return snapshot

    def _workflow_one(
        self,
        entry: dict,
        udid: str,
        steps: List[dict],
        step_fn: WorkflowRunnerFn,
    ) -> None:
        cancel: threading.Event = entry["_cancel"]
        if cancel.is_set():
            with self._lock:
                entry["per_device"][udid]["status"] = "stopped"
            return

        t0 = time.monotonic()
        with self._lock:
            entry["per_device"][udid]["status"] = "running"

        max_attempts = 1 + int(entry["retries"])
        ok_count = 0
        for idx, step in enumerate(steps, 1):
            if cancel.is_set():
                with self._lock:
                    d = entry["per_device"][udid]
                    d["status"] = "stopped"
                    d["duration_ms"] = int(round((time.monotonic() - t0) * 1000))
                self._recompute_progress(entry)
                return

            delay_s = float(step.get("delay_ms", 0)) / 1000.0
            if delay_s > 0 and cancel.wait(delay_s):
                with self._lock:
                    entry["per_device"][udid]["status"] = "stopped"
                self._recompute_progress(entry)
                return

            if step["type"] == "wait":
                wait_s = float(step.get("duration_ms", 0)) / 1000.0
                if wait_s > 0 and cancel.wait(wait_s):
                    with self._lock:
                        entry["per_device"][udid]["status"] = "stopped"
                    self._recompute_progress(entry)
                    return
                ok_count += 1
                with self._lock:
                    d = entry["per_device"][udid]
                    d["ok_steps"] = ok_count
                    d["detail"] = f"step {idx}/{len(steps)}: wait {step['duration_ms']}ms"
                self._recompute_progress(entry)
                continue

            step_ok = False
            last_err = ""
            for attempt in range(1, max_attempts + 1):
                if cancel.is_set():
                    with self._lock:
                        entry["per_device"][udid]["status"] = "stopped"
                    self._recompute_progress(entry)
                    return
                with self._lock:
                    entry["per_device"][udid]["attempts"] += 1
                try:
                    desc = step_fn(udid, step)
                    ok_count += 1
                    with self._lock:
                        d = entry["per_device"][udid]
                        d["ok_steps"] = ok_count
                        d["detail"] = f"step {idx}/{len(steps)}: {desc or step['type']}"
                    self._append_log(entry, udid, "info", f"[{idx}/{len(steps)}] {desc or step['type']} ok")
                    step_ok = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = str(exc)[:240]
                    self._append_log(
                        entry,
                        udid,
                        "warn" if attempt < max_attempts else "error",
                        f"[{idx}/{len(steps)}] {step['type']} failed (attempt {attempt}): {last_err}",
                    )
                    if attempt < max_attempts and cancel.wait(0.4):
                        with self._lock:
                            entry["per_device"][udid]["status"] = "stopped"
                        self._recompute_progress(entry)
                        return

            self._recompute_progress(entry)
            if not step_ok:
                with self._lock:
                    d = entry["per_device"][udid]
                    d["status"] = "failed"
                    d["error"] = last_err or f"Step {idx} ({step['type']}) failed"
                    d["duration_ms"] = int(round((time.monotonic() - t0) * 1000))
                self._recompute_progress(entry)
                return

        with self._lock:
            d = entry["per_device"][udid]
            d["status"] = "ok"
            d["duration_ms"] = int(round((time.monotonic() - t0) * 1000))
        self._recompute_progress(entry)

    def _run_workflow_worker(
        self,
        entry: dict,
        steps: List[dict],
        step_fn: WorkflowRunnerFn,
    ) -> None:
        try:
            targets: List[str] = entry["targets"]
            if entry["mode"] == "serial" or len(targets) == 1:
                for u in targets:
                    if entry["_cancel"].is_set():
                        with self._lock:
                            entry["per_device"][u]["status"] = "stopped"
                        continue
                    self._workflow_one(entry, u, steps, step_fn)
            else:
                with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
                    futs = [pool.submit(self._workflow_one, entry, u, steps, step_fn) for u in targets]
                    for f in futs:
                        with suppress(Exception):
                            f.result()
        finally:
            self._finalize_job(entry)

    def list_jobs(self) -> List[dict]:
        with self._lock:
            return [self._public_job(self._jobs[jid]) for jid in reversed(self._order) if jid in self._jobs]

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            entry = self._jobs.get(job_id)
            if not entry:
                raise AppError(ErrorCode.NOT_FOUND, f"Batch job '{job_id}' not found")
            return self._public_job(entry)

    def stop_job(self, job_id: str) -> dict:
        with self._lock:
            entry = self._jobs.get(job_id)
            if not entry:
                raise AppError(ErrorCode.NOT_FOUND, f"Batch job '{job_id}' not found")
            entry["_cancel"].set()
            if entry["status"] == "running":
                entry["status"] = "stopped"
                entry["finished_at"] = time.time()
                for d in entry["per_device"].values():
                    if d["status"] in ("pending", "running"):
                        d["status"] = "stopped"
            self._append_log(entry, "hub", "warn", "Batch job stopped by user")
            return self._public_job(entry)


batch_service = BatchService()
