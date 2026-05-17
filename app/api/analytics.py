from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .deps import require_admin
from ..db import get_db
from ..models import Admin, AuditLog, ImpressionAggregate

router = APIRouter()


@router.get("/overview")
def overview(from_ts: datetime, to_ts: datetime, device_id: str | None = None, _: object = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(ImpressionAggregate).filter(ImpressionAggregate.minute_utc >= from_ts, ImpressionAggregate.minute_utc <= to_ts)
    if device_id:
        q = q.filter(ImpressionAggregate.device_id == device_id)

    device_plays = (
        q.with_entities(ImpressionAggregate.device_id, func.sum(ImpressionAggregate.play_count), func.sum(ImpressionAggregate.people_count))
        .group_by(ImpressionAggregate.device_id)
        .all()
    )
    ad_plays = (
        q.with_entities(ImpressionAggregate.asset_id, func.sum(ImpressionAggregate.play_count), func.sum(ImpressionAggregate.people_count))
        .group_by(ImpressionAggregate.asset_id)
        .all()
    )
    hour_bucket = func.date_trunc(text("'hour'"), ImpressionAggregate.minute_utc).label("hour_bucket")
    hourly = (
        q.with_entities(hour_bucket, func.sum(ImpressionAggregate.play_count), func.sum(ImpressionAggregate.people_count))
        .group_by(hour_bucket)
        .order_by(hour_bucket)
        .all()
    )

    ad_sorted_by_viewers = sorted(ad_plays, key=lambda x: int(x[2] or 0), reverse=True)

    return {
        "views_per_device": [{"device_id": str(d), "views": int(v or 0), "viewers": int(p or 0)} for d, v, p in device_plays],
        "views_per_ad": [{"asset_id": str(a), "views": int(v or 0), "viewers": int(p or 0)} for a, v, p in ad_plays],
        "hourly": [{"hour": h.isoformat(), "views": int(v or 0), "viewers": int(p or 0)} for h, v, p in hourly],
        "top_ads": [{"asset_id": str(a), "views": int(v or 0), "viewers": int(p or 0)} for a, v, p in ad_sorted_by_viewers[:10]],
        "low_ads": [{"asset_id": str(a), "views": int(v or 0), "viewers": int(p or 0)} for a, v, p in list(reversed(ad_sorted_by_viewers[-10:]))],
    }



@router.delete("/data")
def delete_analytics(
    from_ts: datetime,
    to_ts: datetime,
    device_id: str | None = None,
    admin: Admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(ImpressionAggregate).filter(
        ImpressionAggregate.minute_utc >= from_ts,
        ImpressionAggregate.minute_utc <= to_ts,
    )
    if device_id:
        q = q.filter(ImpressionAggregate.device_id == device_id)
    deleted = q.delete(synchronize_session=False)
    db.add(AuditLog(
        admin_id=admin.id,
        action="delete_analytics",
        entity_type="analytics",
        entity_id=device_id or "all",
        meta_json={"from_ts": from_ts.isoformat(), "to_ts": to_ts.isoformat(), "deleted": deleted},
    ))
    db.commit()
    return {"ok": True, "deleted": deleted}

