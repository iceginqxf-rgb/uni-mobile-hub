"""Tests for Issue #21: batch install & multi-device workflow orchestration."""

from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import Flask

from api.batch_api import bp as batch_bp
from services.batch_service import BatchService, validate_workflow_steps
from services.device_models import MobileDevice
from services.reservation_service import ReservationError
from services.runtime_state import state
from utils.app_errors import AppError


def _wait_done(svc: BatchService, job_id: str, timeout: float = 4.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = svc.get_job(job_id)
        if cur["status"] != "running":
            return cur
        time.sleep(0.02)
    return svc.get_job(job_id)


class TestBatchService(unittest.TestCase):
    def setUp(self):
        self._prev = dict(state.devices)
        state.devices.clear()
        state.upsert_device(MobileDevice(udid="AND-1", name="Phone A", platform="android"))
        state.upsert_device(MobileDevice(udid="AND-2", name="Phone B", platform="android"))
        state.upsert_device(MobileDevice(udid="IOS-1", name="Phone I", platform="ios"))

    def tearDown(self):
        state.devices.clear()
        state.devices.update(self._prev)

    def test_validate_workflow_steps(self):
        with self.assertRaises(AppError):
            validate_workflow_steps([])
        with self.assertRaises(AppError):
            validate_workflow_steps([{"type": "open_app"}])

        steps = validate_workflow_steps([
            {"type": "open_app", "bundle_id": "com.example.app"},
            {"type": "tap", "nx": 1.2, "ny": -0.1},
            {"type": "text", "text": "hello", "enter": True},
            {"type": "screenshot"},
            {"type": "close_app", "package": "com.example.app"},
        ])
        self.assertEqual(steps[0], {"type": "open_app", "app": "com.example.app", "delay_ms": 0})
        self.assertEqual(steps[1]["nx"], 1.0)
        self.assertEqual(steps[1]["ny"], 0.0)
        self.assertTrue(steps[2]["enter"])
        self.assertEqual(steps[3]["type"], "screenshot")

    def test_batch_install_retries_mismatch_and_cleanup(self):
        fd, pkg = tempfile.mkstemp(suffix=".apk")
        os.close(fd)
        with open(pkg, "wb") as fh:
            fh.write(b"PK\x03\x04dummy-apk")

        attempts = {}

        def fake_install(udid: str, path: str):
            attempts[udid] = attempts.get(udid, 0) + 1
            if udid == "AND-2" and attempts[udid] == 1:
                raise RuntimeError("transient adb disconnect")
            return {"installed": True, "detail": "Success"}

        svc = BatchService()
        job = svc.start_install(
            targets=["AND-1", "AND-2", "IOS-1"],
            package_path=pkg,
            filename="demo.apk",
            mode="parallel",
            retries=1,
            cleanup_path=True,
            installer=fake_install,
        )
        final = _wait_done(svc, job["id"])
        self.assertEqual(final["status"], "partial")
        self.assertEqual(final["ok_targets"], 2)
        self.assertEqual(final["failed_targets"], 1)
        self.assertEqual(final["per_device"]["AND-1"]["status"], "ok")
        self.assertEqual(final["per_device"]["AND-2"]["status"], "ok")
        self.assertEqual(final["per_device"]["AND-2"]["attempts"], 2)
        self.assertEqual(final["per_device"]["IOS-1"]["status"], "failed")
        self.assertIn("Platform mismatch", final["per_device"]["IOS-1"]["error"])
        self.assertFalse(os.path.exists(pkg))

    def test_batch_workflow_serial_and_flask_api(self):
        executed = []

        class _FakeControl:
            def launch_app(self, udid, app):
                executed.append(("open_app", udid, app))

            def tap(self, udid, body, *, skip_sync=False):
                executed.append(("tap", udid, skip_sync))

            def input_text(self, udid, body, *, skip_sync=False):
                executed.append(("text", udid, body["text"], skip_sync))

            def key(self, udid, name, *, skip_sync=False):
                executed.append(("key", udid, name, skip_sync))

            def terminate_app(self, udid, app):
                executed.append(("close_app", udid, app))

        svc = BatchService()
        steps = [
            {"type": "open_app", "app": "com.demo.app"},
            {"type": "tap", "nx": 0.5, "ny": 0.5},
            {"type": "text", "text": "hi", "enter": True},
            {"type": "wait", "duration_ms": 10},
            {"type": "close_app", "app": "com.demo.app"},
        ]
        with patch("services.batch_service.ios_control_service", _FakeControl()):
            job = svc.start_workflow(["AND-1", "IOS-1"], steps, mode="serial", retries=0, name="Serial Smoke")
            final = _wait_done(svc, job["id"])

        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["progress_pct"], 100)
        self.assertEqual(final["per_device"]["AND-1"]["ok_steps"], 5)
        self.assertEqual(final["per_device"]["IOS-1"]["ok_steps"], 5)
        # Serial ordering: AND-1 finishes before IOS-1 begins
        and_last_idx = max(i for i, e in enumerate(executed) if e[1] == "AND-1")
        ios_first_idx = min(i for i, e in enumerate(executed) if e[1] == "IOS-1")
        self.assertLess(and_last_idx, ios_first_idx)

        app = Flask(__name__)
        app.register_blueprint(batch_bp)
        with (
            patch("api.batch_api.batch_service", svc),
            patch("api.batch_api.auth_service.current_user", return_value={"id": 3, "username": "u", "role": "user"}),
        ):
            with patch("api.batch_api.reservations.assert_owner", side_effect=ReservationError("locked")):
                with app.test_client() as client:
                    r_deny = client.post("/api/batch/workflow", json={"targets": ["AND-1"], "steps": [{"type": "wait", "duration_ms": 10}]})
                    self.assertEqual(r_deny.status_code, 403)

            with (
                patch("api.batch_api.reservations.assert_owner", return_value=None),
                patch("services.batch_service.IOSAppService.install", return_value={"installed": True}),
            ):
                with app.test_client() as client:
                    r_inst = client.post(
                        "/api/batch/install",
                        data={"targets": '["AND-1"]', "file": (io.BytesIO(b"apkbytes"), "app.apk")},
                        content_type="multipart/form-data",
                    )
                    self.assertEqual(r_inst.status_code, 200)
                    inst_id = r_inst.get_json()["data"]["job"]["id"]
                    inst_final = _wait_done(svc, inst_id)
                    self.assertEqual(inst_final["status"], "completed")

                    r_wf = client.post(
                        "/api/batch/workflow",
                        json={"targets": ["AND-1"], "steps": [{"type": "wait", "duration_ms": 15000}]},
                    )
                    self.assertEqual(r_wf.status_code, 200)
                    wf_id = r_wf.get_json()["data"]["job"]["id"]

                    r_stop = client.post(f"/api/batch/jobs/{wf_id}/stop", json={})
                    self.assertEqual(r_stop.status_code, 200)
                    self.assertEqual(r_stop.get_json()["data"]["job"]["status"], "stopped")

                    r_list = client.get("/api/batch/jobs")
                    self.assertEqual(r_list.status_code, 200)
                    self.assertGreaterEqual(len(r_list.get_json()["data"]["jobs"]), 3)
                    self.assertEqual(client.get("/api/batch/jobs/missing").status_code, 404)
