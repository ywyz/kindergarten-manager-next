"""Offline, deployment-side provisioning entry for online collaboration.

This is intentionally a separate CLI, never an HTTP admin endpoint.  The
deployment operator supplies ``KGM_COLLAB_DATABASE_URL`` (SQLAlchemy
``mysql+pymysql://`` form) and ``KGM_COLLAB_TOKEN_PEPPER``, creates the stable
school/class/teacher directory, and issues a one-time high-entropy bearer
token.  The preview
secret is not needed for provisioning.  The plaintext token is printed only
once; the database stores only its keyed digest.

Example::

    python -m app.collaboration.provision create-school --name "示例幼儿园"
    python -m app.collaboration.provision create-class \
        --school-id <school-uuid> --name "中一班"
    python -m app.collaboration.provision register-class \
        --class-id <class-uuid> --grade middle --class-number 1
    python -m app.collaboration.provision create-term \
        --school-id <school-uuid> --name "2026 秋季学期" \
        --start-date 2026-09-01 --end-date 2027-01-31
    python -m app.collaboration.provision create-teacher \
        --school-id <school-uuid> --name "王老师"
    python -m app.collaboration.provision issue-token --teacher-id <teacher-uuid>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from .class_promotion_models import (
    GRADES,
    ClassPromotionState,
    CollaborationTerm,
    make_class_name,
)
from .config import CollaborationSettings
from .models import Classroom, School, Teacher, TeacherToken
from .security import issue_bearer_token


def _settings() -> CollaborationSettings:
    settings = CollaborationSettings.from_env(require_preview_secret=False)
    settings.validate(require_preview_secret=False)
    return settings


def _session_factory(settings: CollaborationSettings):
    from sqlalchemy.orm import sessionmaker

    from .db import create_collaboration_engine

    engine = create_collaboration_engine(settings)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _create_school(session, name: str) -> dict:
    name = name.strip()
    if not (1 <= len(name) <= 120):
        raise ValueError("school name must be 1..120 characters")
    with session.begin():
        row = School(name=name)
        session.add(row)
        session.flush()
        return {"school_id": str(row.id), "name": row.name}


def _create_class(session, school_id: UUID, name: str) -> dict:
    name = name.strip()
    if not (1 <= len(name) <= 120):
        raise ValueError("class name must be 1..120 characters")
    with session.begin():
        school = session.get(School, school_id)
        if school is None:
            raise ValueError("school not found")
        row = Classroom(school_id=school_id, display_name=name)
        session.add(row)
        session.flush()
        return {
            "class_id": str(row.id),
            "school_id": str(school_id),
            "display_name": row.display_name,
        }


def _create_term(
    session,
    school_id: UUID,
    name: str,
    start_date: str,
    end_date: str,
) -> dict:
    name = name.strip()
    if not (1 <= len(name) <= 80):
        raise ValueError("term name must be 1..80 characters")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("term dates must be YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("term start date must not be after end date")
    with session.begin():
        school = session.scalars(
            select(School).where(School.id == school_id).with_for_update()
        ).one_or_none()
        if school is None:
            raise ValueError("school not found")
        overlap = session.scalars(
            select(CollaborationTerm)
            .where(
                CollaborationTerm.school_id == school_id,
                CollaborationTerm.start_date <= end,
                CollaborationTerm.end_date >= start,
            )
            .with_for_update()
        ).first()
        if overlap is not None:
            raise ValueError("term overlaps an existing school term")
        row = CollaborationTerm(
            school_id=school_id,
            name=name,
            start_date=start,
            end_date=end,
        )
        session.add(row)
        session.flush()
        return {
            "term_id": str(row.id),
            "school_id": str(school_id),
            "name": row.name,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
        }


def _register_class(
    session,
    class_id: UUID,
    grade: str,
    class_number: int,
) -> dict:
    if grade not in GRADES:
        raise ValueError("grade must be small, middle or large")
    if not (1 <= class_number <= 99):
        raise ValueError("class number must be between 1 and 99")
    with session.begin():
        classroom = session.scalars(
            select(Classroom)
            .where(Classroom.id == class_id)
            .with_for_update()
        ).one_or_none()
        if classroom is None:
            raise ValueError("class not found")
        existing = session.scalars(
            select(ClassPromotionState)
            .where(ClassPromotionState.class_id == class_id)
            .with_for_update()
        ).one_or_none()
        if existing is not None:
            if (
                existing.base_grade != grade
                or existing.class_number != class_number
            ):
                raise ValueError(
                    "class is already registered with a different grade/number"
                )
            return {
                "class_id": str(class_id),
                "school_id": str(existing.school_id),
                "grade": existing.base_grade,
                "class_number": existing.class_number,
                "version": existing.version,
                "class_name": make_class_name(
                    existing.base_grade, existing.class_number
                ),
                "already_registered": True,
            }
        state = ClassPromotionState(
            class_id=class_id,
            school_id=classroom.school_id,
            class_number=class_number,
            base_grade=grade,
            version=1,
        )
        session.add(state)
        session.flush()
        return {
            "class_id": str(class_id),
            "school_id": str(classroom.school_id),
            "grade": state.base_grade,
            "class_number": state.class_number,
            "version": state.version,
            "class_name": make_class_name(state.base_grade, state.class_number),
            "already_registered": False,
        }


def _create_teacher(session, school_id: UUID, name: str) -> dict:
    name = name.strip()
    if not (1 <= len(name) <= 120):
        raise ValueError("teacher name must be 1..120 characters")
    with session.begin():
        school = session.get(School, school_id)
        if school is None:
            raise ValueError("school not found")
        row = Teacher(school_id=school_id, display_name=name, active=True)
        session.add(row)
        session.flush()
        return {
            "teacher_id": str(row.id),
            "school_id": str(school_id),
            "display_name": row.display_name,
        }


def _issue_token(session, teacher_id: UUID, days: int, pepper: str) -> dict:
    if days < 1 or days > 3650:
        raise ValueError("days must be between 1 and 3650")
    with session.begin():
        teacher = session.get(Teacher, teacher_id)
        if teacher is None or not teacher.active:
            raise ValueError("active teacher not found")
        token, digest = issue_bearer_token(pepper)
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        row = TeacherToken(
            teacher_id=teacher_id,
            token_hash=digest,
            expires_at=expires_at,
        )
        session.add(row)
        session.flush()
        return {
            "token_id": str(row.id),
            "teacher_id": str(teacher_id),
            "expires_at": expires_at.isoformat(),
            "token": token,
            "note": "plaintext token is shown once; store it in the teacher's secure client",
        }


def _revoke_token(session, token_id: UUID) -> dict:
    with session.begin():
        row = session.get(TeacherToken, token_id)
        if row is None:
            raise ValueError("token not found")
        row.revoked_at = datetime.now(timezone.utc)
        session.flush()
        return {
            "token_id": str(row.id),
            "teacher_id": str(row.teacher_id),
            "revoked_at": row.revoked_at.isoformat(),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline provisioning for online collaboration"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    school = sub.add_parser("create-school")
    school.add_argument("--name", required=True)

    classroom = sub.add_parser("create-class")
    classroom.add_argument("--school-id", required=True, type=UUID)
    classroom.add_argument("--name", required=True)

    registration = sub.add_parser("register-class")
    registration.add_argument("--class-id", required=True, type=UUID)
    registration.add_argument("--grade", required=True, choices=GRADES)
    registration.add_argument(
        "--class-number", required=True, type=int, choices=range(1, 100)
    )

    term = sub.add_parser("create-term")
    term.add_argument("--school-id", required=True, type=UUID)
    term.add_argument("--name", required=True)
    term.add_argument("--start-date", required=True)
    term.add_argument("--end-date", required=True)

    teacher = sub.add_parser("create-teacher")
    teacher.add_argument("--school-id", required=True, type=UUID)
    teacher.add_argument("--name", required=True)

    token = sub.add_parser("issue-token")
    token.add_argument("--teacher-id", required=True, type=UUID)
    token.add_argument("--days", type=int, default=30)

    revoke = sub.add_parser("revoke-token")
    revoke.add_argument("--token-id", required=True, type=UUID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = _settings()
        factory = _session_factory(settings)
        with factory() as session:
            if args.command == "create-school":
                _print(_create_school(session, args.name))
            elif args.command == "create-class":
                _print(_create_class(session, args.school_id, args.name))
            elif args.command == "register-class":
                _print(
                    _register_class(
                        session,
                        args.class_id,
                        args.grade,
                        args.class_number,
                    )
                )
            elif args.command == "create-term":
                _print(
                    _create_term(
                        session,
                        args.school_id,
                        args.name,
                        args.start_date,
                        args.end_date,
                    )
                )
            elif args.command == "create-teacher":
                _print(_create_teacher(session, args.school_id, args.name))
            elif args.command == "issue-token":
                _print(
                    _issue_token(
                        session,
                        args.teacher_id,
                        args.days,
                        settings.token_pepper,
                    )
                )
            elif args.command == "revoke-token":
                _print(_revoke_token(session, args.token_id))
            else:
                raise ValueError("unknown command")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI reports safe summary only
        print(f"provisioning failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
