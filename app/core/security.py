from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from urllib.parse import urlencode

import jwt
from passlib.context import CryptContext

from .config import settings

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(raw: str) -> str:
    return pwd_ctx.hash(raw)


def verify_password(raw: str, password_hash: str) -> bool:
    return pwd_ctx.verify(raw, password_hash)


def make_admin_jwt(admin_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.admin_jwt_minutes)
    payload = {"sub": admin_id, "role": "admin", "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_admin_jwt(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])


def make_device_token() -> str:
    return "devtok_" + secrets.token_urlsafe(32)


def make_pairing_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))


def make_signed_asset_url(asset_id: str, expires_seconds: int = 600) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)).timestamp())
    payload = f"{asset_id}:{exp}:{settings.asset_signing_kid}"
    sig = hmac.new(settings.asset_signing_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    query = urlencode({"asset_id": asset_id, "exp": exp, "kid": settings.asset_signing_kid, "sig": sig})
    base = settings.public_api_base.rstrip("/")
    return f"{base}/assets/signed?{query}"


def verify_asset_signature(asset_id: str, exp: int, kid: str, sig: str) -> bool:
    if kid != settings.asset_signing_kid:
        return False
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return False
    payload = f"{asset_id}:{exp}:{kid}"
    expected = hmac.new(settings.asset_signing_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
