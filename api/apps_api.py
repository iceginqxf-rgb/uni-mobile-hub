"""App management HTTP API: list / running / uninstall / install apps."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress

from flask import Blueprint, request

from api import api
from services.ios_app_service import IOSAppService
from services.request_validators import require
from utils.app_errors import AppError, ErrorCode

bp = Blueprint("apps", __name__, url_prefix="/api/devices")
_svc = IOSAppService()


@bp.get("/<udid>/apps")
@api
def list_apps(udid: str):
    system = request.args.get("system", "0") in ("1", "true", "yes")
    return _svc.list_apps(udid, system=system)


@bp.get("/<udid>/running-apps")
@api
def running_apps(udid: str):
    system = request.args.get("system", "0") in ("1", "true", "yes")
    return _svc.running_apps(udid, include_system=system)


@bp.post("/<udid>/apps/uninstall")
@api
def uninstall(udid: str):
    body = request.get_json(silent=True) or {}
    require(body, "bundle_id")
    return _svc.uninstall(udid, str(body["bundle_id"]))


@bp.post("/<udid>/apps/install")
@api
def install(udid: str):
    """Install an uploaded .ipa or .apk (multipart field ``ipa``, ``apk``, or ``file``)."""
    f = request.files.get("ipa") or request.files.get("apk") or request.files.get("file")
    if f is None or not f.filename:
        raise AppError(ErrorCode.BAD_REQUEST, "no package uploaded (multipart field 'ipa'/'apk'/'file')")
    ext = os.path.splitext(f.filename)[1].lower() or ".ipa"
    fd, path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        f.save(path)
        return _svc.install(udid, path)
    finally:
        with suppress(OSError):
            os.remove(path)
