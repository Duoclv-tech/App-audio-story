"""
Offline verification of the server-signed Ed25519 license token.

Token format:  "<payloadB64url>.<signatureB64url>"
  payloadB64url    = base64url(JSON claims)
  signatureB64url  = base64url( Ed25519 signature over the ASCII BYTES of payloadB64url )

The public key is embedded here (hard-coded in the binary). The matching
private key lives only on the storefront server. Verifying the signature proves
the token was issued by the real server; comparing device_id proves it was
issued for THIS machine.
"""
import base64
import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# SPKI PEM public key — the counterpart private key is server-only.
# NEVER fetch this over the network (would allow key-swap attacks); it is baked
# into the binary on purpose. Rotating this key invalidates every token already
# issued to customers, so it must stay fixed for the product's lifetime.
EMBEDDED_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAa+OGVVHqloZEi6Ds0ZkobsCf3rmBb49TBYoyiA0dDDQ=\n"
    "-----END PUBLIC KEY-----\n"
)


def _active_public_key_pem() -> str:
    """The public key to verify with.

    Always the embedded key in a packaged (frozen) build — it can't be swapped.
    In dev only, LICENSE_PUBLIC_KEY_PEM may override it so the activation flow
    can be tested against a staging/mock storefront with its own keypair.
    """
    import os
    from app import paths
    if not paths.is_frozen():
        override = os.environ.get("LICENSE_PUBLIC_KEY_PEM")
        if override:
            return override.replace("\\n", "\n")
        override_file = os.environ.get("LICENSE_PUBLIC_KEY_FILE")
        if override_file and os.path.isfile(override_file):
            with open(override_file, "r", encoding="ascii") as fh:
                return fh.read()
    return EMBEDDED_PUBLIC_KEY_PEM


def _load_public_key() -> Ed25519PublicKey:
    key = load_pem_public_key(_active_public_key_pem().encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("License public key is not an Ed25519 public key")
    return key


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp (e.g. '2026-08-11T00:00:00.000Z')."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def verify_token(token: str, expected_device_id: str) -> tuple[bool, str, dict]:
    """Verify a stored license token fully offline.

    Returns ``(ok, reason, claims)``:
      - signature check (tampering / forgery)
      - device_id in the token must equal this machine's fingerprint
      - grace_expires_at must be in the future (with grace disabled it equals
        license_expires_at, i.e. far future => effectively never expires)

    ``reason`` is a short machine code: "" (ok), "malformed", "bad_signature",
    "device_mismatch", "expired".
    """
    if not token or "." not in token:
        return False, "malformed", {}

    payload_b64, _, sig_b64 = token.partition(".")
    if not payload_b64 or not sig_b64:
        return False, "malformed", {}

    # (1) Signature — verified over the ASCII bytes of the base64url payload,
    # NOT over the decoded JSON (this is how the server signs it).
    try:
        _load_public_key().verify(_b64url_decode(sig_b64), payload_b64.encode("ascii"))
    except InvalidSignature:
        return False, "bad_signature", {}
    except Exception:
        return False, "malformed", {}

    # Decode claims after the signature is proven authentic.
    try:
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False, "malformed", {}

    # (2) Node lock — token must belong to this exact machine.
    if str(claims.get("device_id", "")) != expected_device_id:
        return False, "device_mismatch", claims

    # (3) Token lifetime. With GRACE_DAYS=0 this is far in the future.
    grace = _parse_iso(claims.get("grace_expires_at", ""))
    if grace is not None:
        now = datetime.now(timezone.utc)
        if grace.tzinfo is None:
            grace = grace.replace(tzinfo=timezone.utc)
        if now > grace:
            return False, "expired", claims

    return True, "", claims
