"""Offline, deployment-side provisioning entry for online collaboration.

This is intentionally a separate CLI, never an HTTP admin endpoint.  The
deployment operator supplies ``KGM_COLLAB_DATABASE_URL`` (SQLAlchemy
``postgresql+psycopg://`` form) and ``KGM_COLLAB_TOKEN_PEPPER``, creates the
stable school/class/teacher directory, and issues a one-time high-entropy
bearer token.  The preview secret is not needed for provisioning.  The
plaintext token is printed only once; the database stores only its keyed
digest.

Example::

    python -m app.collaboration.provision create-school --name "示例幼儿园"
    python -m app.collaboration.provision create-class \
        --school-id <school-uuid> --name "中一班"
    python -m app.collaboration.provision create-teacher \
        --school-id <school-uuid> --name "王老师"
    python -m app.collaboration.provision issue-token --teacher-id <teacher-uuid>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

from .config import CollaborationSettings
from .models import Classroom, School, Teacher, TeacherToken
from .security import issue_bearer_token


def _settings() -> CollaborationSettings:
    settings = CollaborationSettings.from_env(require_preview_secret=False)
    settings.validate(require_preview_secret=False)
    return settings


def _session_factory(settings: CollaborationSettings):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
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
