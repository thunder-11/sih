"""Session-backed authentication routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.persistence.models import UserAgencyScope
from auth.utils import create_session_tokens, get_current_user, get_session_payload, revoke_session, rotate_refresh_token, verify_password
from database import get_db
from models import User


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    agency_id: str | None = None
    permissions: list[str] = Field(default_factory=list)
    badge_number: str | None = None
    police_station: str | None = None


def _scope_for(db: Session, user: User) -> tuple[str | None, list[str]]:
    scope = db.query(UserAgencyScope).filter(UserAgencyScope.user_id == user.id, UserAgencyScope.status == "active").first()
    return (scope.agency_id, list(scope.permissions or [])) if scope else (user.primary_agency_id, [])


def _user_payload(db: Session, user: User) -> dict:
    agency_id, permissions = _scope_for(db, user)
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role,
            "agency_id": agency_id, "permissions": permissions, "badge_number": user.badge_number,
            "police_station": user.police_station}


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or user.status != "active" or not verify_password(req.password, user.password_hash):
        raise ApplicationError(code="INVALID_CREDENTIALS", message="Invalid email or password", status_code=401)
    agency_id, permissions = _scope_for(db, user)
    scope = ([f"agency:{agency_id}"] if agency_id else []) + permissions
    access, refresh, expires_at = create_session_tokens(db, user_id=user.id, role=user.role, scope=scope)
    db.commit()
    return LoginResponse(access_token=access, refresh_token=refresh, expires_at=expires_at, user=_user_payload(db, user))


@router.post("/refresh", response_model=LoginResponse)
def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    access, rotated_refresh, expires_at, user_id = rotate_refresh_token(db, req.refresh_token)
    user = db.query(User).filter(User.id == user_id).one()
    db.commit()
    return LoginResponse(access_token=access, refresh_token=rotated_refresh, expires_at=expires_at,
                         user=_user_payload(db, user))


@router.post("/logout", status_code=204)
def logout(payload: dict = Depends(get_session_payload), db: Session = Depends(get_db)):
    revoke_session(db, session_id=payload["sid"])
    db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return UserResponse(**_user_payload(db, current_user))
