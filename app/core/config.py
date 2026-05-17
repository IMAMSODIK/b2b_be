import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


_DOTENV = _load_dotenv()


def _get(name: str, default: str) -> str:
    return os.getenv(name, _DOTENV.get(name, default))


def _resolve_asset_root(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    backend_root = Path(__file__).resolve().parents[2]
    return str((backend_root / path).resolve())


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    database_url: str
    jwt_secret: str
    jwt_alg: str
    admin_jwt_minutes: int
    device_token_days: int
    pairing_code_ttl_minutes: int
    asset_signing_key: str
    asset_signing_kid: str
    asset_root: str
    public_api_base: str
    cors_origins: str
    rate_limit_per_minute: int
    bootstrap_admin_email: str
    bootstrap_admin_password: str


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name, _DOTENV.get(name))
    if value is None:
        return default
    return int(value)


settings = Settings(
    app_name=_get("APP_NAME", "Digital Signage API"),
    app_env=_get("APP_ENV", "dev"),
    database_url=_get("DATABASE_URL", "postgresql+psycopg://b2b_user:passwordku@127.0.0.1:5432/b2b_iklan"),
    jwt_secret=_get("JWT_SECRET", "change-me"),
    jwt_alg=_get("JWT_ALG", "HS256"),
    admin_jwt_minutes=_get_int("ADMIN_JWT_MINUTES", 60),
    device_token_days=_get_int("DEVICE_TOKEN_DAYS", 30),
    pairing_code_ttl_minutes=_get_int("PAIRING_CODE_TTL_MINUTES", 10),
    asset_signing_key=_get("ASSET_SIGNING_KEY", "change-me-signing-key"),
    asset_signing_kid=_get("ASSET_SIGNING_KID", "v1"),
    asset_root=_resolve_asset_root(_get("ASSET_ROOT", "storage/assets")),
    public_api_base=_get("PUBLIC_API_BASE", "http://localhost:8000"),
    cors_origins=_get("CORS_ORIGINS", "http://localhost:3000"),
    rate_limit_per_minute=_get_int("RATE_LIMIT_PER_MINUTE", 120),
    bootstrap_admin_email=_get("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com"),
    bootstrap_admin_password=_get("BOOTSTRAP_ADMIN_PASSWORD", "admin123"),
)
