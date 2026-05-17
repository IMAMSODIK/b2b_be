from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time


@dataclass
class DeviceRuntime:
    ip: str | None = None
    stream_url: str | None = None
    updated_at: float = 0.0


_lock = Lock()
_runtime_by_device: dict[str, DeviceRuntime] = {}


def update_device_runtime(device_id: str, ip: str | None, stream_url: str | None) -> None:
    with _lock:
        _runtime_by_device[device_id] = DeviceRuntime(ip=ip, stream_url=stream_url, updated_at=time())


def get_device_runtime(device_id: str) -> DeviceRuntime | None:
    with _lock:
        return _runtime_by_device.get(device_id)
