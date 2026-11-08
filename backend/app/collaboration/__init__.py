"""Optional online collaboration service (independent PostgreSQL runtime)."""

from .app import create_collaboration_app
from .config import CollaborationSettings

__all__ = ["CollaborationSettings", "create_collaboration_app"]
