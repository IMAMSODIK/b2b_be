from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from .config import settings

_buckets: dict[str, deque[datetime]] = defaultdict(deque)


def enforce_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = datetime.utcnow()
    bucket = _buckets[ip]
    window_start = now - timedelta(minutes=1)

    while bucket and bucket[0] < window_start:
        bucket.popleft()

    if len(bucket) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    bucket.append(now)
