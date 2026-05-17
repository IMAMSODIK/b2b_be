from datetime import datetime, time, timedelta, timezone
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from .deps import require_admin
from ..core.config import settings
from ..core.rate_limit import enforce_rate_limit
from ..core.security import hash_text, make_admin_jwt, make_device_token, make_pairing_code, verify_password
from ..db import get_db
from ..models import (
    Admin,
    Asset,
    AuditLog,
    Device,
    DeviceScheduleBinding,
    DeviceStatus,
    DeviceToken,
    PairingCode,
    Playlist,
    PlaylistItem,
    ScheduleException,
    Schedule,
    ScheduleRule,
)
from ..schemas import LoginIn, LoginOut, PairingCodeCreateIn, PairingCodeOut
from ..services.scheduler import resolve_playlist_id
from ..runtime_state import get_device_runtime

router = APIRouter()


@router.post("/auth/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request)
    admin = db.query(Admin).filter(Admin.email == payload.email, Admin.is_active.is_(True)).first()
    if not admin or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = make_admin_jwt(str(admin.id))
    return LoginOut(access_token=token, expires_in=3600)


@router.post("/devices/pairing-code", response_model=PairingCodeOut)
def create_pairing_code(
    payload: PairingCodeCreateIn,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    code = make_pairing_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    row = PairingCode(
        code_hash=hash_text(code),
        expires_at=expires,
        created_by_admin_id=admin.id,
        device_name=payload.device_name,
        location=payload.location,
        timezone=payload.timezone,
    )
    db.add(row)
    db.add(AuditLog(admin_id=admin.id, action="create_pairing_code", entity_type="pairing_code", entity_id=str(row.id), meta_json={"device_name": payload.device_name}))
    db.commit()
    return PairingCodeOut(pairing_code=code, expires_at=expires)


@router.get("/devices")
def list_devices(admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    rows = (
        db.query(Device)
        .filter(Device.status != DeviceStatus.deleted.value)
        .order_by(Device.created_at.desc())
        .all()
    )
    out = []
    for d in rows:
        runtime = get_device_runtime(str(d.id))
        last_ip = runtime.ip if runtime is not None else None
        stream_url = runtime.stream_url if runtime is not None else None
        out.append(
            {
                "id": str(d.id),
                "name": d.name,
                "location": d.location,
                "timezone": d.timezone,
                "status": d.status,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "people_counting_enabled": d.people_counting_enabled,
                "last_ip": last_ip,
                "stream_url": stream_url,
            }
        )
    return out


@router.post("/devices/{device_id}/people-counting")
def set_people_counting(device_id: str, enabled: bool, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")
    device.people_counting_enabled = enabled
    device.config_version += 1
    db.add(AuditLog(admin_id=admin.id, action="set_people_counting", entity_type="device", entity_id=device_id, meta_json={"enabled": enabled}))
    db.commit()
    return {"ok": True, "device_id": device_id, "enabled": enabled}


@router.post("/assets/upload")
async def upload_asset(file: UploadFile, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    data = await file.read()
    digest = hashlib.sha256(data).hexdigest()
    asset_id = digest[:32]
    root = Path(settings.asset_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{asset_id}.bin"
    if not path.exists():
        path.write_bytes(data)

    row = db.query(Asset).filter(Asset.sha256 == digest).first()
    if not row:
        row = Asset(
            filename=file.filename or f"{asset_id}.bin",
            mime_type=file.content_type or "application/octet-stream",
            sha256=digest,
            size_bytes=len(data),
            storage_path=str(path),
        )
        db.add(row)
        db.flush()
    db.add(AuditLog(admin_id=admin.id, action="upload_asset", entity_type="asset", entity_id=str(row.id), meta_json={"filename": row.filename}))
    db.commit()
    return {"asset_id": str(row.id), "sha256": row.sha256, "size_bytes": row.size_bytes}


@router.get("/assets")
def list_assets(admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    rows = db.query(Asset).order_by(Asset.created_at.desc()).all()
    return [
        {
            "id": str(a.id),
            "filename": a.filename,
            "size_bytes": a.size_bytes,
            "mime_type": a.mime_type,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(Asset).filter(Asset.id == asset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="asset not found")
    db.delete(row)
    db.add(AuditLog(admin_id=admin.id, action="delete_asset", entity_type="asset", entity_id=asset_id, meta_json={}))
    db.commit()
    return {"ok": True}


@router.post("/playlists")
def create_playlist(name: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    pl = Playlist(name=name)
    db.add(pl)
    db.flush()
    db.add(AuditLog(admin_id=admin.id, action="create_playlist", entity_type="playlist", entity_id=str(pl.id), meta_json={"name": name}))
    db.commit()
    return {"id": str(pl.id), "name": pl.name}


@router.get("/playlists")
def list_playlists(admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    rows = db.query(Playlist).order_by(Playlist.created_at.desc()).all()
    out = []
    for row in rows:
        count = db.query(PlaylistItem).filter(PlaylistItem.playlist_id == row.id).count()
        out.append(
            {
                "id": str(row.id),
                "name": row.name,
                "item_count": count,
                "created_at": row.created_at.isoformat(),
            }
        )
    return out


@router.get("/playlists/{playlist_id}/items")
def list_playlist_items(playlist_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    rows = (
        db.query(PlaylistItem)
        .filter(PlaylistItem.playlist_id == playlist_id)
        .order_by(PlaylistItem.position.asc())
        .all()
    )
    return [
        {
            "id": str(i.id),
            "asset_id": str(i.asset_id),
            "position": i.position,
            "duration_sec": i.duration_sec,
        }
        for i in rows
    ]


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="playlist not found")
    db.delete(row)
    db.add(AuditLog(admin_id=admin.id, action="delete_playlist", entity_type="playlist", entity_id=playlist_id, meta_json={}))
    db.commit()
    return {"ok": True}


@router.post("/playlists/{playlist_id}/items")
def add_playlist_item(
    playlist_id: str,
    asset_id: str,
    duration_sec: int = 0,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    max_pos = db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist_id).count()
    item = PlaylistItem(playlist_id=playlist_id, asset_id=asset_id, position=max_pos, duration_sec=duration_sec)
    db.add(item)
    db.add(AuditLog(admin_id=admin.id, action="add_playlist_item", entity_type="playlist", entity_id=playlist_id, meta_json={"asset_id": asset_id, "duration_sec": duration_sec}))
    db.commit()
    return {"ok": True}


@router.post("/schedules/{schedule_id}/rules")
def add_schedule_rule(
    schedule_id: str,
    playlist_id: str,
    days_of_week: str,
    start_time: str,
    end_time: str,
    priority: int = 100,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = ScheduleRule(
        schedule_id=schedule_id,
        playlist_id=playlist_id,
        days_of_week=[int(x) for x in days_of_week.split(",") if x],
        start_time=time.fromisoformat(start_time),
        end_time=time.fromisoformat(end_time),
        priority=priority,
    )
    db.add(rule)
    db.add(AuditLog(admin_id=admin.id, action="add_schedule_rule", entity_type="schedule", entity_id=schedule_id, meta_json={"playlist_id": playlist_id}))
    db.commit()
    return {"ok": True, "rule_id": str(rule.id)}


@router.post("/schedules")
def create_schedule(name: str, timezone: str = "UTC", priority: int = 100, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    schedule = Schedule(name=name, timezone=timezone, priority=priority, active=True)
    db.add(schedule)
    db.flush()
    db.add(AuditLog(admin_id=admin.id, action="create_schedule", entity_type="schedule", entity_id=str(schedule.id), meta_json={"name": name}))
    db.commit()
    return {"id": str(schedule.id), "name": schedule.name}


@router.get("/schedules")
def list_schedules(admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    rows = db.query(Schedule).order_by(Schedule.created_at.desc()).all()
    out = []
    for row in rows:
        rules_count = db.query(ScheduleRule).filter(ScheduleRule.schedule_id == row.id).count()
        out.append(
            {
                "id": str(row.id),
                "name": row.name,
                "timezone": row.timezone,
                "priority": row.priority,
                "active": row.active,
                "rules_count": rules_count,
                "created_at": row.created_at.isoformat(),
            }
        )
    return out


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="schedule not found")
    db.delete(row)
    db.add(AuditLog(admin_id=admin.id, action="delete_schedule", entity_type="schedule", entity_id=schedule_id, meta_json={}))
    db.commit()
    return {"ok": True}


@router.patch("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: str,
    name: str | None = None,
    timezone: str | None = None,
    priority: int | None = None,
    active: bool | None = None,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="schedule not found")
    if name is not None:
        row.name = name
    if timezone is not None:
        row.timezone = timezone
    if priority is not None:
        row.priority = priority
    if active is not None:
        row.active = active
    db.add(AuditLog(admin_id=admin.id, action="update_schedule", entity_type="schedule", entity_id=schedule_id, meta_json={"name": name, "timezone": timezone}))
    db.commit()
    return {"id": str(row.id), "name": row.name, "timezone": row.timezone, "priority": row.priority, "active": row.active}


@router.get("/schedules/{schedule_id}/rules")
def list_schedule_rules(schedule_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    rules = db.query(ScheduleRule).filter(ScheduleRule.schedule_id == schedule_id).order_by(ScheduleRule.priority.desc()).all()
    return [
        {
            "id": str(r.id),
            "playlist_id": str(r.playlist_id),
            "days_of_week": r.days_of_week,
            "start_time": r.start_time.isoformat() if r.start_time else None,
            "end_time": r.end_time.isoformat() if r.end_time else None,
            "priority": r.priority,
        }
        for r in rules
    ]


@router.delete("/schedules/{schedule_id}/rules/{rule_id}")
def delete_schedule_rule(schedule_id: str, rule_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(ScheduleRule).filter(ScheduleRule.id == rule_id, ScheduleRule.schedule_id == schedule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    db.delete(rule)
    db.add(AuditLog(admin_id=admin.id, action="delete_schedule_rule", entity_type="schedule", entity_id=schedule_id, meta_json={"rule_id": rule_id}))
    db.commit()
    return {"ok": True}


@router.post("/schedules/{schedule_id}/exceptions")
def add_schedule_exception(
    schedule_id: str,
    playlist_id: str,
    starts_at_utc: datetime,
    ends_at_utc: datetime,
    priority: int = 100,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = ScheduleException(
        schedule_id=schedule_id,
        playlist_id=playlist_id,
        starts_at_utc=starts_at_utc,
        ends_at_utc=ends_at_utc,
        priority=priority,
    )
    db.add(row)
    db.add(AuditLog(admin_id=admin.id, action="add_schedule_exception", entity_type="schedule", entity_id=schedule_id, meta_json={"playlist_id": playlist_id}))
    db.commit()
    return {"ok": True, "exception_id": str(row.id)}


@router.post("/devices/{device_id}/bind-schedule")
def bind_schedule(
    device_id: str,
    schedule_id: str,
    priority: int = 100,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = DeviceScheduleBinding(device_id=device_id, schedule_id=schedule_id, priority=priority)
    db.add(row)
    db.add(AuditLog(admin_id=admin.id, action="bind_schedule", entity_type="device", entity_id=device_id, meta_json={"schedule_id": schedule_id}))
    db.commit()
    return {"ok": True, "binding_id": str(row.id)}


@router.get("/device-bindings")
def list_device_bindings(admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    bindings = db.query(DeviceScheduleBinding).all()
    devices_map = {str(d.id): d for d in db.query(Device).filter(Device.status != DeviceStatus.deleted.value).all()}
    schedules_map = {str(s.id): s for s in db.query(Schedule).all()}
    out = []
    for b in bindings:
        device = devices_map.get(str(b.device_id))
        schedule = schedules_map.get(str(b.schedule_id))
        if not device or not schedule:
            continue
        out.append({
            "binding_id": str(b.id),
            "device_id": str(b.device_id),
            "device_name": device.name,
            "device_location": device.location,
            "schedule_id": str(b.schedule_id),
            "schedule_name": schedule.name,
            "schedule_timezone": schedule.timezone,
            "priority": b.priority,
        })
    return out


@router.delete("/device-bindings/{binding_id}")
def delete_device_binding(binding_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(DeviceScheduleBinding).filter(DeviceScheduleBinding.id == binding_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="binding not found")
    device_id = str(row.device_id)
    schedule_id = str(row.schedule_id)
    db.delete(row)
    db.add(AuditLog(admin_id=admin.id, action="unbind_schedule", entity_type="device", entity_id=device_id, meta_json={"schedule_id": schedule_id}))
    db.commit()
    return {"ok": True}


@router.get("/schedules/preview-now")
def preview_now(device_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    _ = admin
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    bindings = db.query(DeviceScheduleBinding).filter(
        (DeviceScheduleBinding.device_id == device.id) | (DeviceScheduleBinding.group_id == device.group_id)
    ).all()
    schedule_ids = [b.schedule_id for b in sorted(bindings, key=lambda r: (-r.priority, str(r.id)))]
    rules = db.query(ScheduleRule).filter(ScheduleRule.schedule_id.in_(schedule_ids)).all() if schedule_ids else []
    exceptions = db.query(ScheduleException).filter(ScheduleException.schedule_id.in_(schedule_ids)).all() if schedule_ids else []

    now = datetime.now(timezone.utc)
    playlist_id, source = resolve_playlist_id(now, device.timezone, rules, exceptions)
    return {
        "device_id": device_id,
        "server_time_utc": now.isoformat(),
        "resolved_playlist_id": playlist_id,
        "rule_source": source,
        "config_version": device.config_version,
    }


@router.post("/devices/{device_id}/rotate-token")
def rotate_device_token(device_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    db.query(DeviceToken).filter(DeviceToken.device_id == device.id, DeviceToken.revoked_at.is_(None)).update(
        {DeviceToken.revoked_at: datetime.now(timezone.utc)}
    )

    plain = make_device_token()
    db.add(
        DeviceToken(
            device_id=device.id,
            token_hash=hash_text(plain),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    device.token_version += 1
    db.add(AuditLog(admin_id=admin.id, action="rotate_device_token", entity_type="device", entity_id=device_id, meta_json={}))
    db.commit()
    return {"device_id": device_id, "device_token": plain}


@router.post("/devices/{device_id}/deactivate")
def deactivate_device(device_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")
    device.status = DeviceStatus.deactivated.value
    db.query(DeviceToken).filter(DeviceToken.device_id == device.id, DeviceToken.revoked_at.is_(None)).update(
        {DeviceToken.revoked_at: datetime.now(timezone.utc)}
    )
    db.add(AuditLog(admin_id=admin.id, action="deactivate_device", entity_type="device", entity_id=device_id, meta_json={}))
    db.commit()
    return {"ok": True}


@router.delete("/devices/{device_id}")
def delete_device(device_id: str, admin: Admin = Depends(require_admin), db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")
    device.status = DeviceStatus.deleted.value
    db.query(DeviceToken).filter(DeviceToken.device_id == device.id, DeviceToken.revoked_at.is_(None)).update(
        {DeviceToken.revoked_at: datetime.now(timezone.utc)}
    )
    db.add(AuditLog(admin_id=admin.id, action="delete_device", entity_type="device", entity_id=device_id, meta_json={}))
    db.commit()
    return {"ok": True}
