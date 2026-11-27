"""Trajectory replay REST API (/api/replay/*)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from api import api
from services import auth_service
from services import reservation_service as reservations
from services.replay_service import replay_service
from utils.app_errors import ErrorCode, err

bp = Blueprint("replay", __name__, url_prefix="/api/replay")


def _body() -> dict:
    return request.get_json(silent=True) or {}


@bp.post("/run")
def run_replay():
    body = _body()
    targets = body.get("targets") or []
    user = auth_service.current_user()
    if user is not None and isinstance(targets, list):
        for udid in targets:
            u = str(udid or "").strip()
            if not u:
                continue
            try:
                reservations.assert_owner(u, user)
            except reservations.ReservationError as exc:
                return jsonify(err(ErrorCode.RESERVATION_DENIED, str(exc))), 403

    @api
    def _start():
        job = replay_service.start_replay(
            targets=targets,
            raw_steps=body.get("steps"),
            speed=body.get("speed", 1.0),
            loops=body.get("loops", 1),
            name=str(body.get("name") or ""),
        )
        return {"job": job}

    return _start()


@bp.get("/jobs")
@api
def list_replay_jobs():
    return {"jobs": replay_service.list_jobs()}


@bp.get("/jobs/<job_id>")
@api
def get_replay_job(job_id: str):
    return {"job": replay_service.get_job(job_id)}


@bp.post("/jobs/<job_id>/stop")
@api
def stop_replay_job(job_id: str):
    return {"job": replay_service.stop_job(job_id)}
