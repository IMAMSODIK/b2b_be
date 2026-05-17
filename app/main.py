from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .api import admin, analytics, device
from .core.config import settings
from .core.security import hash_password, verify_asset_signature
from .db import Base, SessionLocal, engine
from .models import Admin, Asset


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.strip() for s in settings.cors_origins.split(",") if s.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def startup_create_tables():
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            exists = db.query(Admin).filter(Admin.email == settings.bootstrap_admin_email).first()
            if not exists:
                db.add(
                    Admin(
                        email=settings.bootstrap_admin_email,
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        is_active=True,
                    )
                )
                db.commit()
        finally:
            db.close()

    @app.get("/health")
    def health():
        return {"ok": True, "env": settings.app_env}

    @app.get("/assets/signed")
    def signed_asset(asset_id: str = Query(...), exp: int = Query(...), kid: str = Query(...), sig: str = Query(...)):
        if not verify_asset_signature(asset_id, exp, kid, sig):
            raise HTTPException(status_code=403, detail="invalid signature")

        try:
            asset_uuid = UUID(asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid asset id") from exc

        db = SessionLocal()
        try:
            row = db.query(Asset).filter(Asset.id == asset_uuid).first()
        finally:
            db.close()

        if not row:
            raise HTTPException(status_code=404, detail="asset metadata not found")

        file_path = Path(row.storage_path)
        if not file_path.is_absolute():
            file_path = Path(settings.asset_root) / file_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="asset not found")
        return FileResponse(path=file_path)

    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    app.include_router(analytics.router, prefix="/api/admin/analytics", tags=["analytics"])
    app.include_router(device.router, prefix="/api/device", tags=["device"])

    return app


app = create_app()
