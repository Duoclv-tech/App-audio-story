"""
HTTP client for the storefront license API (activation / online re-verify).

Only called when the user activates (or, in grace mode, when refreshing a token
that has expired). Every later launch verifies offline and never touches the
network. Maps the server's machine-readable ``reason`` codes to friendly
Vietnamese messages for the UI.
"""
from typing import Optional

import requests
from loguru import logger

from app.config import settings

# reason code (from server) -> Vietnamese message shown to the user
_ERROR_MESSAGES = {
    "license_not_found": "Mã kích hoạt không đúng hoặc không tồn tại. Vui lòng kiểm tra lại.",
    "order_not_paid": "Đơn hàng chưa được thanh toán. Vui lòng liên hệ nơi bán.",
    "revoked": "Giấy phép này đã bị thu hồi. Vui lòng liên hệ hỗ trợ.",
    "device_limit_reached": "Mã này đã được kích hoạt trên tối đa số máy cho phép. Vui lòng liên hệ hỗ trợ để được gỡ bớt thiết bị.",
    "device_not_activated": "Máy này chưa được kích hoạt.",
    "rate_limited": "Bạn thao tác quá nhanh. Vui lòng đợi một lát rồi thử lại.",
    "network": "Không kết nối được máy chủ kích hoạt. Vui lòng kiểm tra mạng rồi thử lại.",
    "server_error": "Máy chủ kích hoạt gặp sự cố. Vui lòng thử lại sau.",
    "bad_request": "Dữ liệu kích hoạt không hợp lệ.",
}


def message_for(reason: str) -> str:
    return _ERROR_MESSAGES.get(reason, "Kích hoạt thất bại. Vui lòng thử lại.")


def activate(license_key: str, device_id: str) -> dict:
    """Call POST /api/licenses/activate on the storefront.

    Returns a normalized dict:
      { ok: bool, reason: str, message: str, token: Optional[str], data: dict }
    ``token`` is the signed license_token to persist (may be None if the server
    has no signing key configured).
    """
    url = f"{settings.LICENSE_SERVER_URL.rstrip('/')}/api/licenses/activate"
    payload = {
        "license_key": license_key,
        "device_id": device_id,
        "app_version": settings.APP_VERSION,
    }
    try:
        resp = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as exc:
        logger.warning(f"License activate network error: {exc}")
        return {"ok": False, "reason": "network", "message": message_for("network"),
                "token": None, "data": {}}

    return _handle_response(resp)


def verify(license_key: str, device_id: Optional[str]) -> dict:
    """Call POST /api/licenses/verify (grace-mode token refresh only)."""
    url = f"{settings.LICENSE_SERVER_URL.rstrip('/')}/api/licenses/verify"
    payload: dict = {"license_key": license_key, "app_version": settings.APP_VERSION}
    if device_id:
        payload["device_id"] = device_id
    try:
        resp = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as exc:
        logger.warning(f"License verify network error: {exc}")
        return {"ok": False, "reason": "network", "message": message_for("network"),
                "token": None, "data": {}}
    return _handle_response(resp)


def _handle_response(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}

    if resp.status_code == 200 and data.get("valid"):
        return {
            "ok": True,
            "reason": data.get("reason", "activated"),
            "message": "",
            "token": data.get("license_token"),  # may be None if server key absent
            "data": data,
        }

    if resp.status_code == 429:
        reason = "rate_limited"
    elif resp.status_code == 403:
        reason = data.get("reason", "revoked")
    elif resp.status_code == 400:
        reason = "bad_request"
    elif resp.status_code >= 500:
        reason = "server_error"
    else:
        reason = data.get("reason", "server_error")

    return {"ok": False, "reason": reason, "message": message_for(reason),
            "token": None, "data": data}
