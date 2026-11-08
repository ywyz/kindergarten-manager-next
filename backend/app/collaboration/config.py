"""Independent configuration for the optional online collaboration service.

The collaboration service is deliberately separate from the local SQLite
runtime.  It refuses to start without an explicit MySQL 8.4 URL and two
high-entropy secrets; there is no empty/default fallback and no implicit
SQLite mode.  Only ``mysql+pymysql`` is accepted at runtime.  The historical
PostgreSQL SQL is retained unchanged as a record, not as a runtime fallback.
Secrets are excluded from ``repr`` and are never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# Retained only as a historical PostgreSQL migration fact.  The ORM is
# schema-less: the selected database in the URL is the collaboration database.
COLLABORATION_SCHEMA = "collaboration"
DATABASE_SCHEMES = ("mysql+pymysql",)
MIN_SECRET_CHARS = 32
DEFAULT_PREVIEW_TTL_SECONDS = 600
MIN_PREVIEW_TTL_SECONDS = 60
MAX_PREVIEW_TTL_SECONDS = 3600


@dataclass(frozen=True)
class CollaborationSettings:
    database_url: str = field(repr=False)
    token_pepper: str = field(repr=False)
    preview_secret: str = field(repr=False)
    preview_ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS

    @classmethod
    def from_env(
        cls, *, require_preview_secret: bool = True
    ) -> "CollaborationSettings":
        ttl_text = os.environ.get(
            "KGM_COLLAB_PREVIEW_TTL_SECONDS",
            str(DEFAULT_PREVIEW_TTL_SECONDS),
        )
        try:
            ttl = int(ttl_text)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "KGM_COLLAB_PREVIEW_TTL_SECONDS must be an integer"
            ) from exc
        settings = cls(
            database_url=os.environ.get("KGM_COLLAB_DATABASE_URL", "").strip(),
            token_pepper=os.environ.get("KGM_COLLAB_TOKEN_PEPPER", ""),
            preview_secret=os.environ.get("KGM_COLLAB_PREVIEW_SECRET", ""),
            preview_ttl_seconds=ttl,
        )
        settings.validate(require_preview_secret=require_preview_secret)
        return settings

    def validate(self, *, require_preview_secret: bool = True) -> None:
        if not self.database_url:
            raise RuntimeError("KGM_COLLAB_DATABASE_URL is required")
        parsed = urlsplit(self.database_url)
        if parsed.scheme not in DATABASE_SCHEMES:
            raise RuntimeError(
                "KGM_COLLAB_DATABASE_URL must use mysql+pymysql://"
            )
        if not parsed.hostname:
            raise RuntimeError("KGM_COLLAB_DATABASE_URL must include a host")
        if not parsed.path or parsed.path == "/":
            raise RuntimeError("KGM_COLLAB_DATABASE_URL must include a database")
        if len(self.token_pepper) < MIN_SECRET_CHARS:
            raise RuntimeError(
                f"KGM_COLLAB_TOKEN_PEPPER must be at least {MIN_SECRET_CHARS} characters"
            )
        if require_preview_secret and len(self.preview_secret) < MIN_SECRET_CHARS:
            raise RuntimeError(
                f"KGM_COLLAB_PREVIEW_SECRET must be at least {MIN_SECRET_CHARS} characters"
            )
        if not (
            MIN_PREVIEW_TTL_SECONDS
            <= self.preview_ttl_seconds
            <= MAX_PREVIEW_TTL_SECONDS
        ):
            raise RuntimeError(
                "KGM_COLLAB_PREVIEW_TTL_SECONDS must be between "
                f"{MIN_PREVIEW_TTL_SECONDS} and {MAX_PREVIEW_TTL_SECONDS}"
            )
