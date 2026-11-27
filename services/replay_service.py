"""Cross-OS normalized trajectory validation and background multi-device replay."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from services.ios_control_service import ios_control_service
from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode
from utils.logging_setup import get_logger

_log = get_logger(__name__)

_SUPPORTED_TYPES = {"tap", "doubletap", "longpress", "swipe", "button", "key", "text", "wait"}
_MAX_STEPS = 500
_MAX_JOBS = 25

StepRunner = Callable[[str, dict], None]


def _clamp(val: Any, lo: float, hi: float, name: str) -> float:
    try:
        num = float(val)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.BAD_REQUEST, f"Invalid numeric field '{name}'") from exc
    if num != num:  # NaN check
        raise AppError(ErrorCode.BAD_REQUEST, f"Invalid numeric field '{name}'")
    return max(lo, min(hi, num))


def validate_steps(raw_steps: Any) -> List[dict]:
    """Validate and normalize a list of recorded trajectory steps."""
    if not isinstance(raw_steps, list) or not raw_steps:
        raise AppError(ErrorCode.BAD_REQUEST, "Field 'steps' must be a non-empty list")
    if len(raw_steps) > _MAX_STEPS:
        raise AppError(ErrorCode.BAD_REQUEST, f"Too many steps (max {_MAX_STEPS})")

    out: List[dict] = []
    for idx, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} must be an object")
        stype = str(raw.get("type") or "").strip().lower()
        if stype not in _SUPPORTED_TYPES:
            raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} has unsupported type '{stype}'")

        delay_ms = int(round(_clamp(raw.get("delay_ms", 0), 0.0, 60000.0, "delay_ms")))
        step: dict = {"type": stype, "delay_ms": delay_ms}

        if stype in ("tap", "doubletap", "longpress"):
            if raw.get("nx") is None or raw.get("ny") is None:
                raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} ({stype}) requires nx and ny")
            step["nx"] = round(_clamp(raw["nx"], 0.0, 1.0, "nx"), 5)
            step["ny"] = round(_clamp(raw["ny"], 0.0, 1.0, "ny"), 5)
            if stype == "longpress":
                step["duration"] = round(_clamp(raw.get("duration", 0.8), 0.05, 10.0, "duration"), 3)
        elif stype == "swipe":
            for k in ("nx1", "ny1", "nx2", "ny2"):
                if raw.get(k) is None:
                    raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} (swipe) requires {k}")
                step[k] = round(_clamp(raw[k], 0.0, 1.0, k), 5)
            step["duration"] = round(_clamp(raw.get("duration", 0.3), 0.05, 10.0, "duration"), 3)
        elif stype in ("button", "key"):
            name = str(raw.get("name") or "").strip().lower()
            if not name:
                raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} ({stype}) requires name")
            step["name"] = name
        elif stype == "text":
            text = str(raw.get("text") if raw.get("text") is not None else "")
            if not text:
                raise AppError(ErrorCode.BAD_REQUEST, f"Step {idx} (text) requires non-empty text")
            step["text"] = text
        elif stype == "wait":
            step["duration_ms"] = int(round(_clamp(raw.get("duration_ms", 1000), 0.0, 60000.0, "duration_ms")))
        out.append(step)
    return out


def _default_step_runner(udid: str, step: dict) -> None:
    state.touch(udid)
    stype = step["type"]
    if stype == "tap":
        ios_control_service.tap(udid, {"nx": step["nx"], "ny": step["ny"]}, skip_sync=True)
    elif stype == "doubletap":
        ios_control_service.double_tap(udid, {"nx": step["nx"], "ny": step["ny"]}, skip_sync=True)
    elif stype == "longpress":
        ios_control_service.long_press(
            udid, {"nx": step["nx"], "ny": step["ny"], "duration": step["duration"]}, skip_sync=True
        )
    elif stype == "swipe":
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
    elif stype == "button":
        ios_control_service.button(udid, step["name"], skip_sync=True)
    elif stype == "key":
        ios_control_service.key(udid, step["name"], skip_sync=True)
    elif stype == "text":
        ios_control_service.input_text(udid, {"text": step["text"]}, skip_sync=True)


class ReplayService:
    """In-memory background replay orchestrator supporting parallel cross-OS execution."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, dict] = {}
        self._order: List[str] = []

    @staticmethod
    def _public_job(entry: dict) -> dict:
        return {
            "id": entry["id"],
            "name": entry["name"],
            "targets": list(entry["targets"]),
            "status": entry["status"],
            "speed": entry["speed"],
            "loops": entry["loops"],
            "current_loop": entry["current_loop"],
            "current_step": entry["current_step"],
            "total_steps": entry["total_steps"],
            "progress_pct": entry["progress_pct"],
            "per_device": {u: dict(stats) for u, stats in entry["per_device"].items()},
            "started_at": entry["started_at"],
            "finished_at": entry["finished_at"],
        }

    def start_replay(
        self,
        targets: Any,
        raw_steps: Any,
        *,
        speed: Any = 1.0,
        loops: Any = 1,
        name: str = "",
        runner: Optional[StepRunner] = None,
    ) -> dict:
        if not isinstance(targets, list):
            raise AppError(ErrorCode.BAD_REQUEST, "Field 'targets' must be a list of device UDIDs")
        clean_targets = []
        seen = set()
        for t in targets:
            u = str(t or "").strip()
            if u and u not in seen:
                seen.add(u)
                clean_targets.append(u)
        if not clean_targets:
            raise AppError(ErrorCode.BAD_REQUEST, "At least one target device is required")

        steps = validate_steps(raw_steps)
        speed_val = round(_clamp(speed if speed is not None else 1.0, 0.25, 4.0, "speed"), 2)
        loops_val = int(round(_clamp(loops if loops is not None else 1, 1.0, 20.0, "loops")))
        job_id = uuid.uuid4().hex[:12]
        cancel_ev = threading.Event()
        entry = {
            "id": job_id,
            "name": str(name or "").strip() or f"Replay {job_id[:6]}",
            "targets": clean_targets,
            "status": "running",
            "speed": speed_val,
            "loops": loops_val,
            "current_loop": 0,
            "current_step": 0,
            "total_steps": len(steps) * loops_val,
            "progress_pct": 0,
            "per_device": {u: {"ok": 0, "errors": 0, "last_error": ""} for u in clean_targets},
            "started_at": time.time(),
            "finished_at": None,
            "_cancel": cancel_ev,
        }

        with self._lock:
            self._jobs[job_id] = entry
            self._order.append(job_id)
            while len(self._order) > _MAX_JOBS:
                old_id = self._order.pop(0)
                if old_id != job_id:
                    self._jobs.pop(old_id, None)
            snapshot = self._public_job(entry)

        step_fn = runner or _default_step_runner
        t = threading.Thread(
            target=self._run_worker,
            args=(entry, steps, speed_val, loops_val, step_fn),
            name=f"replay-{job_id}",
            daemon=True,
        )
        t.start()
        return snapshot

    def _run_worker(
        self,
        entry: dict,
        steps: List[dict],
        speed: float,
        loops: int,
        step_fn: StepRunner,
    ) -> None:
        cancel: threading.Event = entry["_cancel"]
        targets: List[str] = entry["targets"]
        total = max(1, len(steps) * loops)
        done_count = 0

        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            for loop_idx in range(1, loops + 1):
                if cancel.is_set():
                    break
                with self._lock:
                    entry["current_loop"] = loop_idx
                for step in steps:
                    if cancel.is_set():
                        break
                    delay_s = float(step.get("delay_ms", 0)) / 1000.0 / speed
                    if delay_s > 0 and cancel.wait(delay_s):
                        break
                    if step["type"] == "wait":
                        wait_s = float(step.get("duration_ms", 0)) / 1000.0 / speed
                        if wait_s > 0 and cancel.wait(wait_s):
                            break
                        with self._lock:
                            for u in targets:
                                entry["per_device"][u]["ok"] += 1
                    else:
                        futs = {u: pool.submit(step_fn, u, step) for u in targets}
                        for u, fut in futs.items():
                            err_msg = ""
                            try:
                                fut.result()
                            except Exception as exc:  # noqa: BLE001 — capture per-device failures
                                err_msg = str(exc)[:240]
                            with self._lock:
                                if err_msg:
                                    entry["per_device"][u]["errors"] += 1
                                    entry["per_device"][u]["last_error"] = err_msg
                                else:
                                    entry["per_device"][u]["ok"] += 1
                    done_count += 1
                    with self._lock:
                        entry["current_step"] = done_count
                        entry["progress_pct"] = min(100, int(round((done_count / total) * 100)))

        with self._lock:
            total_ok = sum(s["ok"] for s in entry["per_device"].values())
            total_err = sum(s["errors"] for s in entry["per_device"].values())
            if cancel.is_set() or entry["status"] == "stopped":
                entry["status"] = "stopped"
            elif total_ok == 0 and total_err > 0:
                entry["status"] = "failed"
            else:
                entry["status"] = "completed"
                entry["progress_pct"] = 100
            if entry["finished_at"] is None:
                entry["finished_at"] = time.time()

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            entry = self._jobs.get(job_id)
            if not entry:
                raise AppError(ErrorCode.NOT_FOUND, f"Replay job '{job_id}' not found")
            return self._public_job(entry)

    def list_jobs(self) -> List[dict]:
        with self._lock:
            return [self._public_job(self._jobs[jid]) for jid in reversed(self._order) if jid in self._jobs]

    def stop_job(self, job_id: str) -> dict:
        with self._lock:
            entry = self._jobs.get(job_id)
            if not entry:
                raise AppError(ErrorCode.NOT_FOUND, f"Replay job '{job_id}' not found")
            entry["_cancel"].set()
            if entry["status"] == "running":
                entry["status"] = "stopped"
                entry["finished_at"] = time.time()
            return self._public_job(entry)


replay_service = ReplayService()
