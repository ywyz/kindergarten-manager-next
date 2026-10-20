"""Opaque identifier generation with no application configuration imports.

``app.security.generate_id`` historically generated these IDs, but that
module loads legacy settings (environment/dotenv/session configuration).
The local (desktop) package and the shared content-validation rules must
be able to generate the same identifiers without touching that
configuration, so the primitive lives here and ``app.security`` keeps a
compatible delegate.
"""

import secrets


def new_opaque_id() -> str:
    """Return a new opaque stable identifier (22 url-safe characters).

    16 random bytes encode to 22 url-safe characters, unchanged from the
    reviewed I1 identifier form.
    """
    return secrets.token_urlsafe(16)
