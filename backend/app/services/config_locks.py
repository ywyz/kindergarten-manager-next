"""FOR UPDATE row lockers for I2 configuration (request-local sessions)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Class,
    ConfigurationChange,
    SchoolSettings,
    Term,
)
from app.services import auth_service
from app.services.config_errors import (
    ConfigServiceError,
    PreviewNotFound,
    TermNotFound,
)


def lock_school(db: Session) -> SchoolSettings:
    row = db.execute(
        select(SchoolSettings)
        .where(SchoolSettings.id == "singleton")
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise ConfigServiceError("school settings missing")
    return row


def lock_class(db: Session, class_id: str) -> Class:
    row = db.execute(
        select(Class)
        .where(Class.id == class_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise auth_service.ClassNotFound()
    return row


def lock_term(db: Session, term_id: str) -> Term:
    row = db.execute(
        select(Term)
        .where(Term.id == term_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise TermNotFound()
    return row


def lock_change(db: Session, change_id: str) -> ConfigurationChange:
    row = db.execute(
        select(ConfigurationChange)
        .where(ConfigurationChange.id == change_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise PreviewNotFound()
    return row


def validate_admin_locked(account, snapshot) -> None:
    if account is None or not account.is_active:
        raise auth_service.AuthRequired()
    if account.auth_version != snapshot.auth_version:
        raise auth_service.AuthRequired()
    if account.role != "admin":
        from app.services.config_errors import PreviewForbidden

        raise PreviewForbidden()
