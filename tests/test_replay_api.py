"""Tests for Issue #20: normalized trajectory validation & multi-device replay."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from flask import Flask

from api.replay_api import bp as replay_bp
from services.replay_service import ReplayService, validate_steps
from services.reservation_service import ReservationError
from utils.app_errors import AppError


class TestReplayService(unittest.TestCase):
    def test_validate_steps_rejects_bad_input_and_clamps_coords(self):
        with self.assertRaises(AppError):
            validate_steps([])
        with self.assertRaises(AppError):
            validate_steps([{"type": "unknown_action"}])

        cleaned = validate_steps([
            {"type": "tap", "nx": 1.4, "ny": -0.2, "delay_ms": 50},
            {"type": "swipe", "nx1": 0.2, "ny1": 0.8, "nx2": 0.2, "ny2": 0.2, "duration": 20},
            {"type": "Wait", "duration_ms": 300},
        ])
        self.assertEqual(cleaned[0]["nx"], 1.0)
        self.assertEqual(cleaned[0]["ny"], 0.0)
        self.assertEqual(cleaned[1]["duration"], 10.0)
        self.assertEqual(cleaned[2]["type"], "wait")

    def test_multi_device_replay_and_skip_sync(self):
        calls = []

        class _FakeControl:
            def tap(self, udid, body, *, skip_sync=False):
                calls.append(("tap", udid, body, skip_sync))
                return {"x": 100, "y": 200}

            def button(self, udid, name, *, skip_sync=False):
                calls.append(("button", udid, name, skip_sync))
                return {"button": name}

        svc = ReplayService()
        steps = [
            {"type": "tap", "nx": 0.5, "ny": 0.5, "delay_ms": 0},
            {"type": "wait", "duration_ms": 10, "delay_ms": 0},
            {"type": "button", "name": "home", "delay_ms": 0},
        ]
        with patch("services.replay_service.ios_control_service", _FakeControl()):
            job = svc.start_replay(
                targets=["DEV-IOS", "DEV-AND", "DEV-IOS"],
                raw_steps=steps,
                speed=2.0,
                loops=1,
                name="CrossOS Demo",
            )
            self.assertEqual(job["targets"], ["DEV-IOS", "DEV-AND"])

            deadline = time.time() + 3.0
            while time.time() < deadline:
                cur = svc.get_job(job["id"])
                if cur["status"] != "running":
                    break
                time.sleep(0.02)

        final = svc.get_job(job["id"])
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["progress_pct"], 100)
        self.assertEqual(final["per_device"]["DEV-IOS"]["ok"], 3)
        self.assertEqual(final["per_device"]["DEV-AND"]["ok"], 3)
        self.assertTrue(all(skip is True for _, _, _, skip in calls))
        self.assertEqual(len(calls), 4)

    def test_replay_flask_routes_stop_and_reservation_gate(self):
        svc = ReplayService()
        app = Flask(__name__)
        app.register_blueprint(replay_bp)

        with (
            patch("api.replay_api.replay_service", svc),
            patch("api.replay_api.auth_service.current_user", return_value={"id": 2, "username": "bob", "role": "user"}),
        ):
            # Non-owner gets 403
            with patch("api.replay_api.reservations.assert_owner", side_effect=ReservationError("busy")):
                with app.test_client() as client:
                    r_denied = client.post(
                        "/api/replay/run",
                        json={"targets": ["DEV-1"], "steps": [{"type": "wait", "duration_ms": 50}]},
                    )
                    self.assertEqual(r_denied.status_code, 403)

            # Owner can launch and stop a long wait immediately
            with patch("api.replay_api.reservations.assert_owner", return_value=None):
                with app.test_client() as client:
                    r_run = client.post(
                        "/api/replay/run",
                        json={"targets": ["DEV-1"], "steps": [{"type": "wait", "duration_ms": 15000}]},
                    )
                    self.assertEqual(r_run.status_code, 200)
                    job_id = r_run.get_json()["data"]["job"]["id"]

                    r_list = client.get("/api/replay/jobs")
                    self.assertEqual(r_list.status_code, 200)
                    self.assertEqual(r_list.get_json()["data"]["jobs"][0]["id"], job_id)

                    r_stop = client.post(f"/api/replay/jobs/{job_id}/stop", json={})
                    self.assertEqual(r_stop.status_code, 200)
                    self.assertEqual(r_stop.get_json()["data"]["job"]["status"], "stopped")

                    r_get = client.get(f"/api/replay/jobs/{job_id}")
                    self.assertEqual(r_get.status_code, 200)
                    self.assertEqual(client.get("/api/replay/jobs/missing").status_code, 404)
