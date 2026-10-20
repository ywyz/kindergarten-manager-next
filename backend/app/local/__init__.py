"""Local (desktop) package: independent SQLite data layer and API.

This package is the Architecture v2 local entry point. It deliberately
does not import the legacy ``app.main``/``app.config``/``app.database``/
``app.models``/``app.deps`` modules and never mounts legacy account,
admin, weekly-plan or AI routes. Only reviewed, configuration-free shared
rules are reused from ``app.services`` (content structure, calendar week
math, normalization) and the pure ``app.ids`` primitive.
"""
