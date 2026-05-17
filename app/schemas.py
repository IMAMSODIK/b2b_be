from datetime import datetime, time, date
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PairingCodeCreateIn(BaseModel):
    device_name: str
    location: str
    timezone: str = "UTC"


class PairingCodeOut(BaseModel):
    pairing_code: str
    expires_at: datetime


class DeviceEnrollIn(BaseModel):
    pairing_code: str = Field(min_length=6, max_length=8)
    hostname: str
    app_version: str


class DeviceEnrollOut(BaseModel):
    device_id: str
    device_token: str
    token_expires_at: datetime
    sync_interval_sec: int


class HeartbeatIn(BaseModel):
    free_disk_mb: int
    ip: str
    app_version: str
    stream_url: str | None = None


class ImpressionRowIn(BaseModel):
    minute_utc: datetime
    asset_id: str
    play_count: int
    people_count: int


class ImpressionBatchIn(BaseModel):
    batch_id: str
    rows: list[ImpressionRowIn]


class ScheduleRuleIn(BaseModel):
    playlist_id: str
    days_of_week: list[int]
    start_time: time
    end_time: time
    priority: int = 100
    valid_from: date | None = None
    valid_to: date | None = None
