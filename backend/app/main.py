"""FastAPI application factory for the modular SIH26183 backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.controllers.system import readiness_payload
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.jobs.worker import start_worker_thread
from app.middleware.request_context import RequestContextMiddleware
from app.realtime import ws_manager
from app.schemas.common import StandardError
from database import SessionLocal, init_db
from seed_data import seed_all


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or get_settings()
    runtime.validate_startup()
    configure_logging(runtime.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if not runtime.is_deployed:
            init_db()
        if runtime.fixture_data_enabled:
            db = SessionLocal()
            try:
                seed_all(db)
            finally:
                db.close()
        worker_thread, worker_stop = start_worker_thread(SessionLocal, runtime)
        try:
            yield
        finally:
            worker_stop.set()
            worker_thread.join(timeout=5)

    application = FastAPI(
        title="CFAS — Crypto Fraud Attribution System",
        description="Real-time blockchain forensic intelligence for Indian law enforcement",
        version=runtime.app_version,
        lifespan=lifespan,
        responses={
            status: {"model": StandardError, "description": description}
            for status, description in {
                400: "Invalid request",
                401: "Authentication required",
                403: "Access denied",
                404: "Resource not found",
                409: "State conflict",
                422: "Validation failed",
                429: "Rate limit exceeded",
                500: "Internal error",
                503: "Dependency unavailable",
            }.items()
        },
    )
    application.state.settings = runtime
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)
    install_exception_handlers(application)
    application.include_router(api_router)

    @application.websocket("/ws/trace/{case_id}")
    async def websocket_trace_endpoint(websocket: WebSocket, case_id: str):
        authorization = websocket.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            await websocket.close(code=4401, reason="Authentication required")
            return
        db = SessionLocal()
        try:
            from auth.utils import decode_token
            from app.persistence.models import UserSession
            from app.security.authorization import get_accessible_case
            from models import User
            payload = decode_token(authorization.split(" ", 1)[1])
            session = db.query(UserSession).filter(UserSession.id == payload["sid"],
                                                    UserSession.revoked_at.is_(None)).first()
            user = db.query(User).filter(User.id == payload["sub"], User.status == "active").first()
            if session is None or user is None:
                await websocket.close(code=4401, reason="Session unavailable")
                return
            get_accessible_case(db, user, case_id)
        except Exception:
            await websocket.close(code=4404, reason="Case unavailable")
            return
        finally:
            db.close()
        await ws_manager.connect(case_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(case_id, websocket)

    @application.get("/")
    def root():
        readiness = readiness_payload(runtime)
        return {
            "system": "CFAS — Crypto Fraud Attribution System",
            "version": runtime.app_version,
            "status": readiness["status"],
            "data_mode": runtime.data_mode,
            "endpoints": {
                "docs": "/docs",
                "auth": "/api/v1/auth/login",
                "complaints": "/api/v1/complaints",
                "cases": "/api/v1/cases",
                "dashboard": "/api/v1/dashboard/stats",
                "health": "/health/ready",
                "websocket": "/ws/trace/{case_id}",
            },
        }

    return application


app = create_app()
