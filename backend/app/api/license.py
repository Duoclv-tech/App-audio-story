"""
License API — activation + status for the desktop UI.

These routes are the ONLY /api/v1 endpoints reachable before activation (the
license gate in main.py lets /api/v1/license/* through), so the activation
screen can talk to the backend while everything else stays locked.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.license import service

router = APIRouter()


class ActivateRequest(BaseModel):
    license_key: str = Field(..., min_length=1, max_length=128)


@router.get("/status")
async def license_status():
    """Whether this machine is activated (offline check) + device_id for support."""
    return service.get_status()


@router.post("/activate")
async def license_activate(body: ActivateRequest):
    """Activate this machine online (once). Persists a signed token for offline use."""
    result = service.activate(body.license_key)
    # Always 200: the UI reads `ok`/`message`; avoids leaking HTTP-level detail.
    return result


@router.get("/device")
async def license_device():
    """Return this machine's device_id (so a user can send it to support)."""
    return {"device_id": service.get_device_id()}
