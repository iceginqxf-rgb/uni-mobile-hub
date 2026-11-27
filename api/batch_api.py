"""Batch orchestration REST API (/api/batch/*)."""

from __future__ import annotations

from contextlib import suppress
import json
import os
import tempfile

from flask import Blueprint, jsonify, request

from api import api
from services import auth_service
from services import reservation_service as reservations
from services.batch_service import batch_service
from utils.app_errors import AppError, ErrorCode, err

bp = Blueprint("batch", __name__, url_prefix="/api/batch")


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _check_reservations(targets) -> object | None:
    user = auth_service.current_user()
    if user is None or not isinstance(targets, list):
        return None
    for udid in targets:
        u = str(udid or "").strip()
        if not u:
            continue
        try:
            reservations.assert_owner(u, user)
        except reservations.ReservationError as exc:
            return jsonify(err(ErrorCode.RESERVATION_DENIED, str(exc))), 403
    return None


def _parse_targets_field(raw: str) -> list:
    txt = str(raw or "").strip()
    if not txt:
        return []
    if txt.startswith("["):
        try:
            parsed = json.loads(txt)
            return parsed if isinstance(parsed, list) else []
        except ValueError as exc:
            raise AppError(ErrorCode.BAD_REQUEST, "Invalid JSON in targets field") from exc
    return [x.strip() for x in txt.split(",") if x.strip()]


@bp.post("/install")
def batch_install():
    f = request.files.get("file") or request.files.get("apk") or request.files.get("ipa")
    if f is None or not f.filename:
        @api
        def _missing():
            raise AppError(ErrorCode.BAD_REQUEST, "Missing package file (field 'file'/'apk'/'ipa')")

        return _missing()

    try:
        targets = _parse_targets_field(request.form.get("targets", ""))
    except AppError as exc:
        return jsonify(exc.to_dict()), exc.http_status

    denied = _check_reservations(targets)
    if denied is not None:
        return denied

    ext = os.path.splitext(f.filename)[1].lower()
    fd, path = tempfile.mkstemp(suffix=ext or ".bin")
    os.close(fd)
    try:
        f.save(path)
        job = batch_service.start_install(
            targets=targets,
            package_path=path,
            filename=f.filename,
            mode=request.form.get("mode", "parallel"),
            retries=request.form.get("retries", 0),
            name=request.form.get("name", ""),
            cleanup_path=True,
        )
        return jsonify({"success": True, "data": {"job": job}, "message": "ok"})
    except AppError as exc:
        with suppress(OSError):
            os.remove(path)
        return jsonify(exc.to_dict()), exc.http_status
    except Exception as exc:  # noqa: BLE001
        with suppress(OSError):
            os.remove(path)
        return jsonify(err(ErrorCode.INTERNAL_ERROR, str(exc))), 500


@bp.post("/workflow")
def batch_workflow():
    body = _body()
    targets = body.get("targets") or []
    denied = _check_reservations(targets)
    if denied is not None:
        return denied

    @api
    def _start():
        job = batch_service.start_workflow(
            targets=targets,
            raw_steps=body.get("steps"),
            mode=body.get("mode", "parallel"),
            retries=body.get("retries", 0),
            name=str(body.get("name") or ""),
        )
        return {"job": job}

    return _start()


@bp.get("/jobs")
@api
def list_batch_jobs():
    return {"jobs": batch_service.list_jobs()}


@bp.get("/jobs/<job_id>")
@api
def get_batch_job(job_id: str):
    return {"job": batch_service.get_job(job_id)}


@bp.post("/jobs/<job_id>/stop")
@api
def stop_batch_job(job_id: str):
    return {"job": batch_service.stop_job(job_id)}
