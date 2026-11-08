"""ASGI entry point for the separate collaboration service.

Example deployment command (configuration is mandatory)::

    uvicorn app.collaboration.main:app --host 127.0.0.1 --port 8080

The process refuses to import without ``KGM_COLLAB_DATABASE_URL``,
``KGM_COLLAB_TOKEN_PEPPER`` and ``KGM_COLLAB_PREVIEW_SECRET``.
"""

from .app import create_collaboration_app

app = create_collaboration_app()
