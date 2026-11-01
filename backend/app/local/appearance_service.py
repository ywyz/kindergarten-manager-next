"""Appearance preference read/update (desktop appearance spec §2).

The preference lives in the existing singleton ``local_settings`` row:
``ui_theme`` (light/dark) and ``ui_theme_version`` (strict positive integer).
Appearance updates touch only those two columns.  ``config_version``,
``updated_at``, calendar/game revisions and every business row stay
unchanged, so a theme switch never becomes a configuration change, a dirty
weekly plan or a source-hash input.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.local.errors import (
    LocalAppearanceVersionConflict,
    LocalProfileRequired,
    LocalValidationError,
)
from app.local.profile_service import require_context
from app.local.tx import begin_immediate, read_scope, rollback

THEME_MODES = ("light", "dark")


def _normalize_mode(value: object) -> str:
    if not isinstance(value, str) or value not in THEME_MODES:
        raise LocalValidationError("mode 只能是 light 或 dark")
    return value


def _normalize_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LocalValidationError("expected_version 必须是正整数")
    return value


def _settings(session: Session):
    context = require_context(session, date.today())
    if context.settings is None:  # pragma: no cover - require_context guards
        raise LocalProfileRequired()
    return context.settings


def read_appearance(session: Session) -> dict:
    """Read the current preference inside one explicit read transaction."""
    with read_scope(session):
        settings = _settings(session)
        return {
            "mode": settings.ui_theme,
            "version": settings.ui_theme_version,
        }


def update_appearance(
    session: Session, *, mode: object, expected_version: object
) -> dict:
    """Compare-and-set the preference; never bumps config_version."""
    new_mode = _normalize_mode(mode)
    expected = _normalize_version(expected_version)
    begin_immediate(session)
    try:
        settings = _settings(session)
        if settings.ui_theme_version != expected:
            raise LocalAppearanceVersionConflict(
                details={
                    "mode": settings.ui_theme,
                    "version": settings.ui_theme_version,
                }
            )
        if settings.ui_theme != new_mode:
            settings.ui_theme = new_mode
            settings.ui_theme_version = expected + 1
            session.flush()
        result = {
            "mode": settings.ui_theme,
            "version": settings.ui_theme_version,
        }
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return result
