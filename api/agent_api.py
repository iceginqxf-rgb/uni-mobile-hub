"""Unified AI Agent HTTP API (/api/v1/agent/*).

Provides a flat, cross-OS REST surface for pure-vision AI agents with:
  - Static Bearer Token or X-Agent-Token auth (alongside normal login sessions)
  - Automatic device discovery, reservation check/claim, and connection on demand
  - Normalized 0.0..1.0 coordinates (nx/ny) across Android and iOS screens
"""

from __future__ import annotations

from flask import Blueprint, Response, request

from api import api
from services import auth_service, get_adapter
from services import reservation_service as reservations
from services.ios_control_service import ios_control_service
from services.reservation_service import ReservationError
from services.runtime_state import state
from utils.app_errors import AppError, ErrorCode

bp = Blueprint("agent", __name__, url_prefix="/api/v1/agent")


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _ensure_ready(udid: str):
    dev = state.get_device(udid)
    if dev is None:
        get_adapter().discover()
        dev = state.get_device(udid)
    if dev is None:
        raise AppError(ErrorCode.NOT_FOUND, f"Device '{udid}' is offline or not connected")

    user = auth_service.current_user()
    if not user:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    res = reservations.get(udid)
    if res is not None and res["user_id"] != user["id"] and not auth_service.is_admin(user):
        raise ReservationError(f"设备已被 {res['username']} 占用")
    if res is None and int(user.get("id") or 0) > 0:
        reservations.claim(udid, user)

    if not dev.connected:
        get_adapter(udid).connect(udid)
    state.touch(udid)
    return state.get_device(udid) or dev


def _normalize_app_id(body: dict) -> str:
    app_id = str(body.get("app") or body.get("bundle_id") or body.get("package") or "").strip()
    if not app_id:
        raise AppError(ErrorCode.BAD_REQUEST, "Missing required field: app (or bundle_id / package)")
    return app_id


@bp.route("/devices", methods=["GET"])
@api
def agent_list_devices():
    devices = get_adapter().discover()
    return {"devices": [d.to_dict() for d in devices]}


@bp.route("/devices/<udid>/screenshot", methods=["GET", "POST"])
def agent_screenshot(udid: str):
    fmt = (request.args.get("format") or "").strip().lower()
    if request.method == "POST" or fmt == "json":
        @api
        def _json_shot():
            dev = _ensure_ready(udid)
            shot = ios_control_service.screenshot(udid, as_base64=True)
            shot["width"] = dev.screen_width
            shot["height"] = dev.screen_height
            shot["platform"] = dev.platform
            return shot

        return _json_shot()

    try:
        dev = _ensure_ready(udid)
        raw = ios_control_service.screenshot(udid, as_base64=False)["bytes"]
    except Exception as exc:
        @api
        def _err():
            raise exc

        return _err()

    headers = {
        "Cache-Control": "no-store",
        "X-Device-Platform": dev.platform or "ios",
    }
    if dev.screen_width and dev.screen_height:
        headers["X-Device-Width"] = str(dev.screen_width)
        headers["X-Device-Height"] = str(dev.screen_height)
    return Response(raw, mimetype="image/jpeg", headers=headers)


@bp.post("/devices/<udid>/tap")
@api
def agent_tap(udid: str):
    _ensure_ready(udid)
    return ios_control_service.tap(udid, _body())


@bp.post("/devices/<udid>/doubletap")
@api
def agent_doubletap(udid: str):
    _ensure_ready(udid)
    return ios_control_service.double_tap(udid, _body())


@bp.post("/devices/<udid>/longpress")
@api
def agent_longpress(udid: str):
    _ensure_ready(udid)
    return ios_control_service.long_press(udid, _body())


@bp.post("/devices/<udid>/swipe")
@api
def agent_swipe(udid: str):
    _ensure_ready(udid)
    return ios_control_service.swipe(udid, _body())


@bp.post("/devices/<udid>/text")
@api
def agent_text(udid: str):
    _ensure_ready(udid)
    body = _body()
    res = ios_control_service.input_text(udid, body)
    if body.get("enter"):
        ios_control_service.key(udid, "enter")
        res["enter"] = True
    return res


_BUTTON_NAMES = {
    "home", "back", "recent", "appswitch", "lock", "unlock",
    "power", "wake", "sleep", "rotate", "volumeup", "volumedown", "menu",
}


@bp.post("/devices/<udid>/key")
@api
def agent_key(udid: str):
    _ensure_ready(udid)
    body = _body()
    name = str(body.get("name") or body.get("key") or "").strip().lower()
    if not name:
        raise AppError(ErrorCode.BAD_REQUEST, "Missing required field: name")
    if name in _BUTTON_NAMES:
        return ios_control_service.button(udid, name)
    return ios_control_service.key(udid, name)


@bp.get("/devices/<udid>/apps")
@api
def agent_apps(udid: str):
    _ensure_ready(udid)
    system = (request.args.get("system") or "").strip().lower() in ("1", "true", "yes")
    return get_adapter(udid).list_apps(udid, system=system)


@bp.post("/devices/<udid>/open_app")
@api
def agent_open_app(udid: str):
    _ensure_ready(udid)
    return ios_control_service.launch_app(udid, _normalize_app_id(_body()))


@bp.post("/devices/<udid>/close_app")
@api
def agent_close_app(udid: str):
    _ensure_ready(udid)
    return ios_control_service.terminate_app(udid, _normalize_app_id(_body()))
