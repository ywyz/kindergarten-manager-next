"""Merge supported local todo changes into an actual remote VCALENDAR.

The edit path must never wipe fields the local model does not carry.  This
module rewrites only SUMMARY, the completion state (STATUS + the RFC 5545
``PERCENT-COMPLETE`` property) and — when the date actually changed — DUE;
everything else in the remote object (DESCRIPTION, PRIORITY, VALARM blocks,
RELATED-TO, RRULE, CATEGORIES, an unchanged timed/zone DUE, unknown
properties) is preserved verbatim.

Refusals (controlled ``SYNC_RESPONSE_INVALID``, the remote task is never
touched): anything other than exactly one VCALENDAR with exactly one VTODO,
or a remote UID that differs from the expected one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.local.todo_sync_caldav import (
    _LINE_RE,  # noqa: SLF001
    _escape_ical,  # noqa: SLF001
    TodoSyncError,
)

_REFUSAL = "远端日历结构不受支持，未修改远端任务"


def merge_vtodo(
    raw: str,
    *,
    uid: str,
    title: str,
    due_date: str | None,
    completed: bool,
    dtstamp: str | None = None,
) -> bytes:
    """Return the merged VCALENDAR bytes for one conditional PUT."""
    stamp = dtstamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cal_starts = [
        i for i, line in enumerate(lines) if line.strip() == "BEGIN:VCALENDAR"
    ]
    cal_ends = [
        i for i, line in enumerate(lines) if line.strip() == "END:VCALENDAR"
    ]
    if len(cal_starts) != 1 or len(cal_ends) != 1 or cal_ends[0] < cal_starts[0]:
        raise TodoSyncError("SYNC_RESPONSE_INVALID", _REFUSAL)
    todo_starts = [
        i
        for i, line in enumerate(lines)
        if line.strip() == "BEGIN:VTODO" and cal_starts[0] < i < cal_ends[0]
    ]
    todo_ends = [
        i
        for i, line in enumerate(lines)
        if line.strip() == "END:VTODO" and cal_starts[0] < i < cal_ends[0]
    ]
    if len(todo_starts) != 1 or len(todo_ends) != 1 or todo_ends[0] <= todo_starts[0]:
        raise TodoSyncError("SYNC_RESPONSE_INVALID", _REFUSAL)
    todo_start, todo_end = todo_starts[0], todo_ends[0]
    remote_due_date: str | None = None
    remote_uid: str | None = None
    for index in range(todo_start + 1, todo_end):
        match = _LINE_RE.match(lines[index].strip())
        if match is None:
            continue
        name, value = match.group(1), match.group(2).strip()
        if name == "UID":
            remote_uid = value
        elif name == "DUE" and value[:8].isdigit():
            remote_due_date = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    if remote_uid != uid:
        raise TodoSyncError(
            "SYNC_RESPONSE_INVALID", "远端任务 UID 不一致，未修改远端任务"
        )

    date_changed = (due_date or "") != (remote_due_date or "")
    due_kept = not date_changed
    out: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if index == todo_start:
            out.append(line)
            out.append(f"SUMMARY:{_escape_ical(title)}")
            if date_changed and due_date:
                out.append(f"DUE;VALUE=DATE:{due_date.replace('-', '')}")
                due_kept = True
            out.append("STATUS:COMPLETED" if completed else "STATUS:NEEDS-ACTION")
            out.append(f"PERCENT-COMPLETE:{100 if completed else 0}")
            continue
        if index == todo_end:
            if not due_kept and due_date:
                # The remote had no DUE and the local now sets one.
                out.append(f"DUE;VALUE=DATE:{due_date.replace('-', '')}")
            out.append(line)
            continue
        match = _LINE_RE.match(stripped)
        name = match.group(1) if match is not None else ""
        if index > todo_start and index < todo_end:
            if name == "SUMMARY" or name == "STATUS" or name.startswith("PERCENT-"):
                # Replaced by the written block above.
                continue
            if name == "DUE" and date_changed:
                # The date changed: the old (possibly timed/zone) DUE is
                # replaced by the plain date form written above.
                continue
            # Everything else — DESCRIPTION, PRIORITY, VALARM blocks,
            # RELATED-TO, RRULE, CATEGORIES, an unchanged DUE line, unknown
            # properties — is preserved verbatim.
            out.append(line)
            continue
        out.append(line)
    # Refresh DTSTAMP in the VCALENDAR (replace the first; add after PRODID
    # or after BEGIN:VCALENDAR when the remote had none).
    stamp_seen = False
    for i, item in enumerate(out):
        match = _LINE_RE.match(item.strip())
        if match is not None and match.group(1) == "DTSTAMP":
            out[i] = f"DTSTAMP:{stamp}"
            stamp_seen = True
            break
    if not stamp_seen:
        insert_at = cal_starts[0] + 1
        for i, item in enumerate(out):
            if item.strip().startswith("PRODID:"):
                insert_at = i + 1
                break
        out.insert(insert_at, f"DTSTAMP:{stamp}")
    return ("\r\n".join(out) + "\r\n").encode("utf-8")


__all__ = ["merge_vtodo"]
