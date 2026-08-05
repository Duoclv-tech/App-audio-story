"""
License orchestration — the single entry point used by the API and the gate.

Responsibilities:
- decide whether enforcement is active (always on in the packaged .exe)
- compute/cache this machine's device_id
- activate online (once) and persist the signed token
- verify the stored token offline on every status check / gated request
"""
from typing import Optional

from loguru import logger

from app import paths
from app.config import settings
from app.license import client, store
from app.license.device_id import compute_device_id
from app.license.token import verify_token


# Set ONLY in-process by desktop.py's --selftest (never via env), so the frozen
# build's smoke test can hit protected routes without a real license. A customer
# cannot trigger this: there is no env/config path to it.
_selftest_mode = False


def set_selftest_mode(enabled: bool) -> None:
    global _selftest_mode
    _selftest_mode = enabled


def enforcement_enabled() -> bool:
    """True when the license gate should block unactivated use.

    Always enforced in a frozen (packaged) build so it can't be turned off by
    an env var on a customer machine. In dev it is off unless LICENSE_ENFORCE
    is set true, so development isn't blocked.
    """
    if _selftest_mode:
        return False
    return paths.is_frozen() or settings.LICENSE_ENFORCE


def get_device_id() -> str:
    return compute_device_id()


def is_activated() -> bool:
    """Fast check used by the request gate. Offline verify of the stored token.

    An online-only record (server had no signing key -> token was null) is
    honored ONLY in dev; a packaged (.exe) build rejects it and requires a real
    signed token. See activate().
    """
    record = store.load()
    if not record:
        return False
    if record.get("online_only"):
        # Online-only records carry no signed token, so there is nothing to
        # verify offline. Refuse to honor them in a packaged (.exe) build — a
        # real, signed token is mandatory there (see activate()). Kept working
        # in dev so a keyless mock storefront can still be tested.
        return not paths.is_frozen()
    token = record.get("token")
    if not token:
        return False
    ok, _reason, _claims = verify_token(token, get_device_id())
    return ok


def get_status() -> dict:
    """Full status for the UI / status endpoint."""
    enforced = enforcement_enabled()
    device_id = get_device_id()
    record = store.load()

    if not record:
        return {
            "activated": False,
            "enforced": enforced,
            "device_id": device_id,
            "reason": "no_license",
        }

    if record.get("online_only"):
        # No signed token to verify offline. Only trusted outside a packaged
        # build; in the .exe this record is not enough to unlock.
        activated = not paths.is_frozen()
        return {
            "activated": activated,
            "enforced": enforced,
            "device_id": device_id,
            "online_only": True,
            "reason": None if activated else "online_only_unsupported",
            "product_name": record.get("product_name"),
        }

    token = record.get("token", "")
    ok, reason, claims = verify_token(token, device_id)
    return {
        "activated": ok,
        "enforced": enforced,
        "device_id": device_id,
        "reason": reason or None,
        "product_name": record.get("product_name"),
        "license_key_masked": _mask(record.get("license_key")),
    }


def activate(license_key: str) -> dict:
    """Activate this machine with ``license_key``.

    Returns { ok, message, reason } for the API to surface. On success the
    signed token is verified locally and persisted for offline use.
    """
    license_key = (license_key or "").strip()
    if not (12 <= len(license_key) <= 64):
        return {"ok": False, "reason": "bad_request",
                "message": "Mã kích hoạt phải dài 12–64 ký tự."}

    device_id = get_device_id()
    result = client.activate(license_key, device_id)
    if not result["ok"]:
        return {"ok": False, "reason": result["reason"], "message": result["message"]}

    data = result.get("data", {})
    product_name = data.get("product_name")
    token = result.get("token")

    if not token:
        # Server returned no signed token -> nothing we can verify offline.
        if paths.is_frozen():
            # Packaged (.exe): hard-block the online-only fallback. Without a
            # signed token the license can't be node-locked or re-checked on
            # later launches, so treat activation as failed.
            logger.error("Activation returned no license_token; refusing "
                         "online-only fallback in packaged build.")
            return {"ok": False, "reason": "server_error",
                    "message": "Không thể xác thực giấy phép. Vui lòng bật kết nối "
                               "mạng và thử lại. Nếu vẫn lỗi, hãy liên hệ hỗ trợ."}
        # Dev only: accept online-only so a keyless mock storefront can be tested.
        logger.warning("Activation succeeded but server returned no license_token "
                       "(online-only mode, dev only). Offline verification is unavailable.")
        store.save({
            "online_only": True,
            "license_key": license_key,
            "product_name": product_name,
        })
        return {"ok": True, "reason": "activated_online_only",
                "message": "Kích hoạt thành công.", "product_name": product_name}

    # Sanity-check the freshly issued token against this machine before trusting it.
    ok, reason, _claims = verify_token(token, device_id)
    if not ok:
        logger.error(f"Server-issued token failed local verification: {reason}")
        return {"ok": False, "reason": "server_error",
                "message": "Máy chủ trả về giấy phép không hợp lệ. Vui lòng liên hệ hỗ trợ."}

    store.save({
        "token": token,
        "license_key": license_key,
        "product_name": product_name,
    })
    logger.info("License activated successfully for this device")
    return {"ok": True, "reason": "activated",
            "message": "Kích hoạt thành công.", "product_name": product_name}


def deactivate() -> None:
    """Remove the local license (for support / testing)."""
    store.clear()


def _mask(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "••••"
    return f"{key[:4]}••••{key[-4:]}"
