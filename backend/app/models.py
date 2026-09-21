from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utc_now() -> datetime:
    """Return a naive UTC datetime; MySQL DateTime does not store time zones."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'teacher')", name="ck_account_role"),
        CheckConstraint("username = LOWER(username)", name="ck_username_lowercase"),
        UniqueConstraint("username", name="uq_accounts_username"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    username: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), nullable=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )

    sessions: Mapped[list["AccountSession"]] = relationship(
        "AccountSession", back_populates="account", lazy="dynamic"
    )


class FirstAdminControl(Base):
    __tablename__ = "first_admin_control"
    __table_args__ = (
        CheckConstraint("id = 'singleton'", name="ck_first_admin_control_singleton"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )


class AccountSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64, collation="utf8mb4_bin"), unique=True, nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    account: Mapped["Account"] = relationship("Account", back_populates="sessions")


class OperationRecord(Base):
    __tablename__ = "operation_records"
    __table_args__ = (
        CheckConstraint(
            "operator_type IN ('account', 'server_operator')",
            name="ck_operation_record_operator_type",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Mapped[str] = mapped_column(
        String(32, collation="utf8mb4_bin"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_now, nullable=False
    )
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    operator_type: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    account_version_after: Mapped[int] = mapped_column(Integer, nullable=False)
