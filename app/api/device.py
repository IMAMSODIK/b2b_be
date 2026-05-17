from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .deps import require_device
from ..core.rate_limit import enforce_rate_limit
from ..core.security import hash_text, make_device_token, make_signed_asset_url
from ..db import get_db
from ..models import (
    Asset,
    Device,
    DeviceBatch,
    DeviceScheduleBinding,
    DeviceStatus,
    DeviceToken,
    ImpressionAggregate,
    PairingCode,
    PlaylistItem,
    ScheduleException,
    ScheduleRule,
)
from ..schemas import DeviceEnrollIn, DeviceEnrollOut, HeartbeatIn, ImpressionBatchIn
from ..services.scheduler import resolve_playlist_id
from ..runtime_state import update_device_runtime

router = APIRouter()


@router.post("/enroll", response_model=DeviceEnrollOut)
def enroll(payload: DeviceEnrollIn, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request)
    now = datetime.now(timezone.utc)
    code = (
        db.query(PairingCode)
        .filter(
            PairingCode.code_hash == hash_text(payload.pairing_code),
            PairingCode.used_at.is_(None),
            PairingCode.expires_at > now,
        )
        .first()
    )
    if not code:
        raise HTTPException(status_code=400, detail="invalid or expired pairing code")

    device = Device(
        name=code.device_name,
        location=code.location,
        timezone=code.timezone,
        status=DeviceStatus.active.value,
    )
    db.add(device)
    db.flush()

    token_plain = make_device_token()
    expires = now + timedelta(days=30)
    db.add(DeviceToken(device_id=device.id, token_hash=hash_text(token_plain), expires_at=expires))

    code.used_at = now
    db.commit()

    return DeviceEnrollOut(
        device_id=str(device.id),
        device_token=token_plain,
        token_expires_at=expires,
        sync_interval_sec=30,
    )


@router.post("/heartbeat")
def heartbeat(payload: HeartbeatIn, device: Device = Depends(require_device), db: Session = Depends(get_db)):
    device.last_seen_at = datetime.now(timezone.utc)
    update_device_runtime(str(device.id), payload.ip, payload.stream_url)
    db.commit()
    return {
        "ok": True,
        "status": device.status,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/sync")
def sync(device: Device = Depends(require_device), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)

    binding_rows = db.query(DeviceScheduleBinding).filter(
        (DeviceScheduleBinding.device_id == device.id) | (DeviceScheduleBinding.group_id == device.group_id)
    ).all()
    schedule_ids = [b.schedule_id for b in sorted(binding_rows, key=lambda r: (-r.priority, str(r.id)))]

    rules = db.query(ScheduleRule).filter(ScheduleRule.schedule_id.in_(schedule_ids)).all() if schedule_ids else []
    exceptions = (
        db.query(ScheduleException).filter(ScheduleException.schedule_id.in_(schedule_ids)).all() if schedule_ids else []
    )

    playlist_id, rule_source = resolve_playlist_id(now, device.timezone, rules, exceptions)
    playlist_items = (
        db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist_id).order_by(PlaylistItem.position.asc()).all()
        if playlist_id
        else []
    )
    asset_ids = [item.asset_id for item in playlist_items]
    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).all() if asset_ids else []

    required_assets = [
        {
            "asset_id": str(asset.id),
            "filename": asset.filename,
            "mime_type": asset.mime_type,
            "sha256": asset.sha256,
            "size_bytes": asset.size_bytes,
            "signed_url": make_signed_asset_url(str(asset.id)),
        }
        for asset in assets
    ]

    return {
        "config_version": device.config_version,
        "server_time_utc": now.isoformat(),
        "people_counting_enabled": device.people_counting_enabled,
        "rule_source": rule_source,
        "active_playlist": {
            "id": str(playlist_id) if playlist_id else None,
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "filename": next((a.filename for a in assets if a.id == item.asset_id), None),
                    "mime_type": next((a.mime_type for a in assets if a.id == item.asset_id), None),
                    "duration_sec": item.duration_sec,
                    "position": item.position,
                }
                for item in playlist_items
            ],
        },
        "required_assets": required_assets,
    }


@router.post("/impressions/batch")
def upload_impressions(payload: ImpressionBatchIn, device: Device = Depends(require_device), db: Session = Depends(get_db)):
    existing = db.query(DeviceBatch).filter(DeviceBatch.device_id == device.id, DeviceBatch.batch_id == payload.batch_id).first()
    if existing:
        return {"accepted": 0, "duplicate": True}

    db.add(DeviceBatch(device_id=device.id, batch_id=payload.batch_id, payload_json=payload.model_dump(mode="json")))

    upserts = 0
    for row in payload.rows:
        rec = (
            db.query(ImpressionAggregate)
            .filter(
                ImpressionAggregate.device_id == device.id,
                ImpressionAggregate.asset_id == row.asset_id,
                ImpressionAggregate.minute_utc == row.minute_utc,
            )
            .first()
        )
        if rec:
            rec.play_count += row.play_count
            rec.people_count += row.people_count
        else:
            db.add(
                ImpressionAggregate(
                    device_id=device.id,
                    asset_id=row.asset_id,
                    minute_utc=row.minute_utc,
                    play_count=row.play_count,
                    people_count=row.people_count,
                )
            )
        upserts += 1

    db.commit()
    return {"accepted": upserts, "duplicate": False}
