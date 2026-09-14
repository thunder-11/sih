"""Password, session, and bearer-token security helpers."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.persistence.models import UserSession
from database import get_db


security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode_token(*, user_id: str, role: str, session_id: str, token_type: str, expires_at: datetime) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "role": role, "sid": session_id, "typ": token_type,
         "jti": str(uuid.uuid4()), "iat": now, "exp": expires_at, "iss": "cfas"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_session_tokens(db: Session, *, user_id: str, role: str, scope: list[str]) -> tuple[str, str, datetime]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    access_expires_at = now + timedelta(hours=settings.access_token_expire_hours)
    refresh_expires_at = now + timedelta(hours=settings.refresh_token_expire_hours)
    session = UserSession(user_id=user_id, token_hash="pending", scope=scope, issued_at=now, expires_at=refresh_expires_at)
    db.add(session)
    db.flush()
    access = _encode_token(user_id=user_id, role=role, session_id=session.id, token_type="access", expires_at=access_expires_at)
    refresh = _encode_token(user_id=user_id, role=role, session_id=session.id, token_type="refresh", expires_at=refresh_expires_at)
    session.token_hash = _token_hash(refresh)
    db.flush()
    return access, refresh, access_expires_at


def decode_token(token: str, *, expected_type: str = "access") -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ApplicationError(code="UNAUTHORIZED", message="Invalid or expired token", status_code=401) from exc
    if payload.get("typ") != expected_type or not payload.get("sub") or not payload.get("sid"):
        raise ApplicationError(code="UNAUTHORIZED", message="Invalid token payload", status_code=401)
    return payload


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[str, str, datetime, str]:
    from models import User

    payload = decode_token(refresh_token, expected_type="refresh")
    session = db.query(UserSession).filter(UserSession.id == payload["sid"]).first()
    now = datetime.now(timezone.utc)
    expires_at = session.expires_at if session is not None else now
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (session is None or session.user_id != payload["sub"] or session.revoked_at is not None
            or expires_at <= now or session.token_hash != _token_hash(refresh_token)):
        raise ApplicationError(code="SESSION_REVOKED", message="Session is expired or revoked", status_code=401)
    user = db.query(User).filter(User.id == session.user_id, User.status == "active").first()
    if user is None:
        raise ApplicationError(code="UNAUTHORIZED", message="User is unavailable", status_code=401)
    access_expires_at = now + timedelta(hours=get_settings().access_token_expire_hours)
    refresh_expires_at = now + timedelta(hours=get_settings().refresh_token_expire_hours)
    access = _encode_token(user_id=user.id, role=user.role, session_id=session.id, token_type="access", expires_at=access_expires_at)
    refresh = _encode_token(user_id=user.id, role=user.role, session_id=session.id, token_type="refresh", expires_at=refresh_expires_at)
    session.token_hash = _token_hash(refresh)
    session.expires_at = refresh_expires_at
    session.last_seen_at = now
    db.flush()
    return access, refresh, access_expires_at, user.id


def revoke_session(db: Session, *, session_id: str, reason: str = "logout") -> None:
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        session.revoked_reason = reason
        db.flush()


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security), db: Session = Depends(get_db)):
    from models import User

    if credentials is None:
        raise ApplicationError(code="UNAUTHORIZED", message="Authentication required", status_code=401)
    payload = decode_token(credentials.credentials)
    session = db.query(UserSession).filter(UserSession.id == payload["sid"]).first()
    now = datetime.now(timezone.utc)
    expires_at = session.expires_at if session is not None else now
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if session is None or session.revoked_at is not None or expires_at <= now or session.user_id != payload["sub"]:
        raise ApplicationError(code="SESSION_REVOKED", message="Session is expired or revoked", status_code=401)
    user = db.query(User).filter(User.id == payload["sub"], User.status == "active").first()
    if user is None:
        raise ApplicationError(code="UNAUTHORIZED", message="User not found", status_code=401)
    session.last_seen_at = now
    return user


def get_session_payload(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise ApplicationError(code="UNAUTHORIZED", message="Authentication required", status_code=401)
    return decode_token(credentials.credentials)


def require_role(*roles: str):
    def role_checker(user=Depends(get_current_user)):
        if user.role not in roles:
            raise ApplicationError(code="FORBIDDEN", message="Access denied", status_code=403,
                                   details={"required_roles": list(roles)})
        return user
    return role_checker


def create_access_token(data: dict) -> str:
    """Compatibility helper; request authentication requires a persisted session."""
    expires_at = datetime.now(timezone.utc) + timedelta(hours=get_settings().access_token_expire_hours)
    return _encode_token(user_id=data["sub"], role=data.get("role", "investigator"),
                         session_id=data.get("sid", "legacy-unpersisted"), token_type="access", expires_at=expires_at)
