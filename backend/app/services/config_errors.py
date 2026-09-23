"""I2 configuration service: exceptions and shared engineering limits."""

from datetime import timedelta

PREVIEW_TTL = timedelta(minutes=30)
MAX_HEADER_NAMES = 20
MAX_TERM_DAYS = 2000
MAX_OVERRIDE_DATES = 366
MAX_QUERY_DAYS = 366


class ConfigServiceError(Exception):
    pass


class PreviewNotFound(ConfigServiceError):
    pass


class PreviewStale(ConfigServiceError):
    pass


class PreviewExpired(ConfigServiceError):
    pass


class PreviewForbidden(ConfigServiceError):
    pass


class DependencyNotReady(ConfigServiceError):
    pass


class NoChanges(ConfigServiceError):
    pass


class ClassNameTaken(ConfigServiceError):
    pass


class TermNotFound(ConfigServiceError):
    pass


class TermOverlap(ConfigServiceError):
    pass


class CalendarError(ConfigServiceError):
    pass


class ValidationError(ConfigServiceError, ValueError):
    """Also a ValueError so Pydantic field validators wrap it as 422."""
