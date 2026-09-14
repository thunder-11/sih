"""Liveness, readiness, and configuration-safe system endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.controllers.system import liveness_payload, metrics_payload, readiness_payload, system_status_payload
from auth.utils import get_current_user, require_role
from database import get_db
from models import User


router = APIRouter(tags=["System"])


@router.get("/health/live")
def liveness(request: Request):
    return liveness_payload(request.app.state.settings)


@router.get("/health/ready")
def readiness(request: Request, db: Session = Depends(get_db)):
    return readiness_payload(request.app.state.settings, db)


@router.get("/api/v1/system/status")
def system_status(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return system_status_payload(request.app.state.settings, db)


@router.get("/api/v1/system/metrics")
def system_metrics(user: User = Depends(require_role("admin"))):
    return metrics_payload()
