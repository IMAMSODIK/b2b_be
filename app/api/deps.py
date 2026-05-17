from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..core.security import decode_admin_jwt, hash_text
from ..db import get_db
from ..models import Admin, Device, DeviceStatus, DeviceToken


def require_admin(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Admin:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing admin bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_admin_jwt(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid admin token") from exc

    admin = db.query(Admin).filter(Admin.id == payload.get("sub"), Admin.is_active.is_(True)).first()
    if not admin:
        raise HTTPException(status_code=401, detail="admin not found")
    return admin


def require_device(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Device:
    if not authorization.startswith("Bearer devtok_"):
        raise HTTPException(status_code=401, detail="missing device token")

    token = authorization.removeprefix("Bearer ").strip()
    token_hash = hash_text(token)
    now = datetime.now(timezone.utc)

    token_row = (
        db.query(DeviceToken)
        .filter(
            DeviceToken.token_hash == token_hash,
            DeviceToken.revoked_at.is_(None),
            DeviceToken.expires_at > now,
        )
        .first()
    )
    if not token_row:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    device = db.query(Device).filter(Device.id == token_row.device_id).first()
    if not device or device.status != DeviceStatus.active.value:
        raise HTTPException(status_code=403, detail="device inactive")
    return device
