"""Agency, role, assignment, and explicit case-access enforcement."""

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import ApplicationError
from app.persistence.models import CaseAccessGrant, UserAgencyScope
from models import Case, User


def active_agency_id(db: Session, user: User) -> str:
    now = datetime.now(timezone.utc)
    scope = db.query(UserAgencyScope).filter(
        UserAgencyScope.user_id == user.id,
        UserAgencyScope.status == "active",
        or_(UserAgencyScope.valid_to.is_(None), UserAgencyScope.valid_to > now),
    ).first()
    agency_id = scope.agency_id if scope else user.primary_agency_id
    if not agency_id:
        raise ApplicationError(code="AGENCY_SCOPE_REQUIRED", message="No active agency scope", status_code=403)
    return agency_id


def accessible_case_query(db: Session, user: User):
    agency_id = active_agency_id(db, user)
    query = db.query(Case).filter(Case.agency_id == agency_id)
    if user.role == "investigator":
        grant = db.query(CaseAccessGrant.case_id).filter(
            CaseAccessGrant.user_id == user.id, CaseAccessGrant.revoked_at.is_(None)
        )
        query = query.filter(or_(Case.assigned_officer_id == user.id, Case.id.in_(grant)))
    return query


def get_accessible_case(db: Session, user: User, case_id: str, *, write: bool = False) -> Case:
    case = accessible_case_query(db, user).filter(Case.id == case_id).first()
    if case is None:
        raise ApplicationError(code="CASE_NOT_FOUND", message="Case not found", status_code=404)
    if write and user.role == "compliance_viewer":
        raise ApplicationError(code="FORBIDDEN", message="Case is read-only for this role", status_code=403)
    if write and user.role == "investigator" and case.assigned_officer_id != user.id:
        writable = db.query(CaseAccessGrant).filter(
            CaseAccessGrant.case_id == case.id, CaseAccessGrant.user_id == user.id,
            CaseAccessGrant.permission == "write", CaseAccessGrant.revoked_at.is_(None),
        ).first()
        if writable is None:
            raise ApplicationError(code="FORBIDDEN", message="Case is read-only for this user", status_code=403)
    return case
