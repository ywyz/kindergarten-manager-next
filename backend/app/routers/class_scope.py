"""Shared backend re-judged class context for read/export routes.

One role judgment, used by the I3/I4 read routers and the I5 export router so
Teacher/admin semantics cannot fork across routes (spec word-export
implementation §3.4: class scope is always derived on the backend, never
trusted from the client).

Two ``class_id`` presence semantics are supported on purpose:

* GET query semantics (I3/I4 read routes): whether the client sent the query
  parameter at all — including an empty string — is indistinguishable from
  "non-null" for teachers; ``class_id is not None`` keeps the historical
  behaviour. This is the default when ``class_id_sent`` is omitted.
* JSON body presence (I5 export): an explicit ``class_id: null`` must never be
  treated as "not sent", so callers pass ``class_id_sent`` from the strict
  schema's ``model_fields_set``.

The raised HTTPException shapes (403 FORBIDDEN, 422 VALIDATION_ERROR) are
exactly the ones the I3/I4 routers used before the extraction.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import TeacherAssignment


def resolve_read_class_id(
    db,
    *,
    role: str,
    account_id: str,
    class_id: str | None,
    class_id_sent: bool | None = None,
) -> str:
    """Backend-re-judged class context for one read/export request.

    Admin: must pass a non-empty explicit ``class_id``.
    Teacher: must not send ``class_id`` at all (presence judged per
    ``class_id_sent``); a teacher without a current assignment is 403.
    Any other role is 403.
    """
    if class_id_sent is None:
        class_id_sent = class_id is not None
    if role == "admin":
        if not class_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="VALIDATION_ERROR",
            )
        return class_id
    if role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )
    if class_id_sent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="VALIDATION_ERROR",
        )
    assignment = db.get(TeacherAssignment, account_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
        )
    return assignment.class_id
