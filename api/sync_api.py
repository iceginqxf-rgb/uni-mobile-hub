"""REST endpoints for cross-OS synchronous group control."""

from __future__ import annotations

from flask import Blueprint, request

from api import api
from services import auth_service
from services import reservation_service as reservations
from services.reservation_service import ReservationError
from services.sync_service import sync_service
from utils.app_errors import AppError, ErrorCode

bp = Blueprint("sync", __name__, url_prefix="/api/sync")


def _check_sync_permissions(master: str, slaves: list[str]) -> None:
    user = auth_service.current_user()
    if not user:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    reservations.assert_owner(master, user)
    if not auth_service.is_admin(user):
        for sid in slaves:
            res = reservations.get(sid)
            if res and res["user_id"] != user["id"]:
                raise ReservationError(f"设备已被 {res['username']} 占用")


@bp.route("/status", methods=["GET"])
@api
def sync_status():
    return sync_service.get_status()


@bp.route("/group", methods=["POST"])
@api
def sync_set_group():
    body = request.get_json(silent=True) or {}
    master = str(body.get("master") or "").strip()
    slaves = body.get("slaves") or []
    if not isinstance(slaves, list):
        raise AppError(ErrorCode.BAD_REQUEST, "'slaves' must be a list of device UDIDs")
    if not master:
        raise AppError(ErrorCode.BAD_REQUEST, "Missing required field: master")
    _check_sync_permissions(master, [str(s) for s in slaves])
    return sync_service.set_group(master, [str(s) for s in slaves])


@bp.route("/group", methods=["DELETE"])
@bp.route("/group/<master>", methods=["DELETE"])
@api
def sync_clear_group(master: str | None = None):
    if master:
        user = auth_service.current_user()
        if not user:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
        reservations.assert_owner(master, user)
    else:
        user = auth_service.current_user()
        if not user:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
        if not auth_service.is_admin(user):
            # Non-admins clear only groups whose master they own.
            for m in list(sync_service.get_status().get("groups", {}).keys()):
                res = reservations.get(m)
                if res and res["user_id"] == user["id"]:
                    sync_service.clear_group(m)
            return sync_service.get_status()
    return sync_service.clear_group(master)
