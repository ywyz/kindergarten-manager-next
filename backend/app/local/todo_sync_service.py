"""Optional Nextcloud Tasks (CalDAV) two-way todo sync service.

The feature is strictly opt-in and per local teacher profile: it stays
disabled until the teacher explicitly chooses 「双向同步所选清单（新增、
编辑和完成）」.  The linkage covers creates, edits and completions in both
directions, never propagates deletes in either direction, and never
overwrites a conflicting change: when both sides changed, the item is
skipped and reported with a fixed code.

Boundaries kept by design:

- the Nextcloud *password* lives only in the machine-local DPAPI store
  (:mod:`todo_sync_credentials`): never in SQLite, never in a backup
  package, never in the frontend and never in a log;
- every mutating request owns one ``BEGIN IMMEDIATE`` transaction and one
  immutable operation receipt keyed by ``(profile_id, request_id)`` — a
  duplicate request returns the original receipt, a different fingerprint
  on the same key is a conflict;
- UIDs are deterministic per local todo, creations use ``If-None-Match: *``
  and edits use ``If-Match``, so a retried run never duplicates a task and
  never blindly overwrites a remote edit;
- a remotely deleted task keeps its local todo with the link detached
  (nothing is pushed back); a locally deleted todo removes only its link
  row (the remote task is untouched).

Network calls always run outside write transactions; each item's database
write is one small transaction that re-reads the current local state, so a
teacher edit racing a background sync is never clobbered.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import urllib.parse
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import todo_domain as domain
from app.local.base import utc_now
from app.local.normalize import normalize_request_id
from app.local.todo_repository import SqlTodoRepository
from app.local.todo_sync_caldav import NextcloudTasksClient
from app.local.todo_sync_credentials import (
    NextcloudAccount,
    NextcloudCredentialStore,
    TodoSyncCredentialError,
)
from app.local.todo_sync_models import (
    LocalTodoSyncLink,
    LocalTodoSyncOperation,
    LocalTodoSyncSetting,
)
from app.local.tx import begin_immediate, read_scope, rollback as tx_rollback
from app.local.todo_sync_caldav import TodoSyncError as CalDAVError

MAX_TITLE = 200
UID_SUFFIX = "@kindergarten-manager-next"

# Single-flight background sync: at most one engine run at a time, with one
# bounded re-run when a write lands while a run is finishing.
_sync_gate = threading.Lock()
_sync_in_flight = False
_sync_pending = False
# One engine at a time per running profile: a manual 「立即同步」 and a
# background write-triggered run share this mutex so two engines can never
# process the same remote/local task concurrently (a duplicate link insert
# would otherwise race to a UNIQUE failure).
_engine_lock = threading.Lock()


class TodoSyncServiceError(RuntimeError):
    """Controlled service refusal with a stable public code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def deterministic_uid(todo_id: str) -> str:
    return f"kgm-todo-{todo_id}{UID_SUFFIX}"


def state_hash(title: str, due_date: str | None, completed: bool) -> str:
    raw = f"{title}\n{due_date or ''}\n{int(bool(completed))}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _todo_state(todo: dict[str, Any]) -> str:
    return state_hash(todo["title"], todo["due_date"], bool(todo["completed"]))


def _fingerprint(action: str, payload: dict[str, Any]) -> str:
    import json

    raw = json.dumps(
        {"action": action, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_rollback(session: Session) -> None:
    try:
        tx_rollback(session)
    except Exception:  # noqa: BLE001 - preserve the primary exception
        pass


# ---------------------------------------------------------------------------
# Credential / client helpers
# ---------------------------------------------------------------------------


def _store(runtime) -> NextcloudCredentialStore:
    return NextcloudCredentialStore(runtime.credential_root)


def _account(runtime) -> NextcloudAccount:
    try:
        return _store(runtime).load()
    except TodoSyncCredentialError as exc:
        raise TodoSyncServiceError(exc.code, exc.message, status_code=409) from exc


def _client(runtime, account: NextcloudAccount) -> NextcloudTasksClient:
    factory = getattr(runtime, "todo_sync_transport_factory", None)
    if factory is not None:
        transport = factory(account)
    else:
        from app.local.todo_sync_caldav import HttpsTransport

        transport = HttpsTransport(
            account.url, account.username, account.password
        )
    base_path = urllib.parse.urlsplit(account.url).path.rstrip("/")
    return NextcloudTasksClient(transport, base_path=base_path)


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------


def _setting_row(session: Session, profile_id: str) -> LocalTodoSyncSetting | None:
    return session.get(LocalTodoSyncSetting, profile_id)


def _public_setting(row: LocalTodoSyncSetting | None) -> dict[str, Any]:
    if row is None:
        return {
            "configured": False,
            "enabled": False,
            "setting_version": 0,
        }
    return {
        "configured": True,
        "enabled": bool(row.enabled),
        "server_url": row.server_url,
        "username": row.username,
        "list_href": row.list_href,
        "list_name": row.list_name,
        "setting_version": int(row.setting_version),
        "last_sync_at": (
            row.last_sync_at.isoformat(sep=" ") if row.last_sync_at else None
        ),
        "last_result": row.last_result,
    }


def _machine_identity(runtime) -> dict | None:
    """This machine's stored Nextcloud identity (no password), or None."""
    try:
        return _store(runtime).identity()
    except Exception:  # noqa: BLE001 - identity probe never raises
        return None


def _setting_matches_machine(row, runtime) -> bool:
    """True when the settings row and this machine's credential store name
    the same Nextcloud account (restored profiles bind per machine)."""
    if row is None:
        return True
    identity = _machine_identity(runtime)
    if identity is None:
        return False
    return (
        identity.get("url") == row.server_url
        and identity.get("username") == row.username
    )


def get_status(session: Session, runtime) -> dict[str, Any]:
    """Display-safe linkage state: settings plus credential availability.

    A restored profile's settings row names the ORIGIN account; this
    machine's DPAPI store may hold a different account's password.  The two
    never mix: on a mismatch the credential is reported unusable for this
    setting until the teacher reconnects explicitly.
    """
    with read_scope(session):
        row = _setting_row(session, _profile_id(session))
        credential_status = _store(runtime).status()
    # The mismatch override applies only when this machine's store actually
    # holds a DIFFERENT account identity: an empty/cleared store keeps the
    # store's own status (configured=False after 「停止并清除」).
    identity = _machine_identity(runtime)
    if (
        row is not None
        and identity is not None
        and (
            identity.get("url") != row.server_url
            or identity.get("username") != row.username
        )
    ):
        credential_status = {
            "configured": True,
            "password_available": False,
            "reason": "SYNC_CREDENTIAL_ACCOUNT_MISMATCH",
            "detail": "本机保存的密码属于其他 Nextcloud 账户，请重新连接本档案要用的账户",
        }
    return {
        "setting": _public_setting(row),
        "credential": credential_status,
    }


def _profile_id(session: Session) -> str:
    from app.local.profile_service import require_context

    context = require_context(session, date.today())
    if context.profile is None:  # pragma: no cover - require_context guards
        raise TodoSyncServiceError(
            "SYNC_PROFILE_REQUIRED", "本地档案未就绪", status_code=409
        )
    return context.profile.id


# ---------------------------------------------------------------------------
# Receipts (idempotent by request id)
# ---------------------------------------------------------------------------


def _replay(
    session: Session,
    profile_id: str,
    request_id: str,
    action: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    row = session.get(LocalTodoSyncOperation, (profile_id, request_id))
    if row is None:
        return None
    if row.action != action or row.input_fingerprint != fingerprint:
        raise TodoSyncServiceError(
            "SYNC_REQUEST_CONFLICT", "该请求已用于不同内容", status_code=409
        )
    result = row.result_json
    if not isinstance(result, dict):
        raise TodoSyncServiceError(
            "SYNC_REQUEST_CONFLICT", "原请求回执不可用", status_code=409
        )
    return dict(result)


def _insert_receipt(
    session: Session,
    profile_id: str,
    request_id: str,
    action: str,
    fingerprint: str,
    result: dict[str, Any],
) -> None:
    session.add(
        LocalTodoSyncOperation(
            profile_id=profile_id,
            request_id=request_id,
            action=action,
            input_fingerprint=fingerprint,
            result_json=result,
            created_at=utc_now(),
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Connect / lists / select / disable
# ---------------------------------------------------------------------------


def connect_account(
    session: Session,
    runtime,
    *,
    request_id: object,
    url: object,
    username: object,
    password: object,
) -> dict[str, Any]:
    """Validate + probe one Nextcloud account and persist it (still off).

    The connection check is a real bounded PROPFIND; the password is stored
    only in the machine-local DPAPI store.  Nothing is enabled here — the
    teacher must still pick a list and explicitly choose two-way sync.
    """
    rid = normalize_request_id(request_id)
    fingerprint = _fingerprint(
        "connect", {"url": str(url or ""), "username": str(username or "")}
    )
    profile_id = _profile_id(session)
    replay = _replay(session, profile_id, rid, "connect", fingerprint)
    if replay is not None:
        return replay
    # Validate and probe FIRST with a transient account: a failed connect
    # keeps the previous settings row and DPAPI credentials untouched.
    from app.local.todo_sync_credentials import (
        NextcloudAccount as _NextcloudAccount,
        validate_password as _validate_password,
        validate_server_url as _validate_server_url,
        validate_username as _validate_username,
    )

    try:
        normalized = _validate_server_url(url)
        user = _validate_username(username)
        secret = _validate_password(password)
    except TodoSyncCredentialError as exc:
        raise TodoSyncServiceError(exc.code, exc.message, status_code=422) from exc
    transient = _NextcloudAccount(url=normalized, username=user, password=secret)
    try:
        probe = _client(runtime, transient).probe_connection()
    except CalDAVError as exc:
        # Nothing was stored: the previous linkage and credentials survive a
        # failed connect intact.
        raise TodoSyncServiceError(exc.code, exc.message, status_code=502) from exc
    try:
        store = _store(runtime)
        store.save(url=normalized, username=user, password=secret)
    except TodoSyncCredentialError as exc:
        raise TodoSyncServiceError(exc.code, exc.message, status_code=409) from exc
    begin_immediate(session)
    try:
        row = _setting_row(session, profile_id)
        account_changed = (
            row is not None
            and (row.server_url != normalized or row.username != user)
        )
        if row is None:
            session.add(
                LocalTodoSyncSetting(
                    profile_id=profile_id,
                    enabled=False,
                    server_url=normalized,
                    username=user,
                    setting_version=1,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        else:
            row.server_url = normalized
            row.username = user
            row.setting_version = int(row.setting_version) + 1
            row.updated_at = utc_now()
        if account_changed:
            # Switching accounts invalidates the chosen list binding (the
            # selection belonged to the previous account).  Local todos and
            # their links are kept untouched: link scoping by the selected
            # list href keeps the previous account's items isolated (never
            # pulled into, never pushed to the new account), and the teacher
            # must explicitly select a list before sync runs again.
            row.enabled = False
            row.list_href = None
            row.list_name = None
        result = {
            "ok": True,
            "server_url": normalized,
            "username": user,
            "principal_reported": probe.get("principal") is not None,
            "enabled": False,
            "setting_version": (
                int(row.setting_version) if row is not None else 1
            ),
        }
        _insert_receipt(session, profile_id, rid, "connect", fingerprint, result)
        session.commit()
    except BaseException:
        _safe_rollback(session)
        raise
    return result


_MISMATCH_CODE = "SYNC_CREDENTIAL_ACCOUNT_MISMATCH"


def _require_setting_account(row, runtime) -> None:
    """Refuse account-bound CalDAV access on a restored/mismatched profile."""
    if row is not None and not _setting_matches_machine(row, runtime):
        raise TodoSyncServiceError(
            _MISMATCH_CODE,
            "本机保存的密码属于其他 Nextcloud 账户，请先重新连接本档案要用的账户",
            status_code=409,
        )


def list_lists(session: Session, runtime) -> dict[str, Any]:
    row = _setting_row(session, _profile_id(session))
    _require_setting_account(row, runtime)
    account = _account(runtime)
    client = _client(runtime, account)
    try:
        probe = client.probe_connection()
        home = client.calendar_home(probe.get("principal"))
        lists = client.list_lists(home)
    except CalDAVError as exc:
        raise TodoSyncServiceError(exc.code, exc.message, status_code=502) from exc
    return {
        "lists": [
            {
                "href": item.href,
                "display_name": item.display_name,
                "supports_vtodo": item.supports_vtodo,
            }
            for item in lists
        ],
        "selected": row.list_href if row is not None else None,
        "enabled": bool(row.enabled) if row is not None else False,
    }


def select_list(
    session: Session,
    runtime,
    *,
    request_id: object,
    expected_version: object,
    list_href: object,
) -> dict[str, Any]:
    """The explicit teacher choice: bind one list and enable two-way sync."""
    rid = normalize_request_id(request_id)
    if not isinstance(expected_version, int):
        raise TodoSyncServiceError(
            "SYNC_INPUT_INVALID", "设置版本必须是整数", status_code=422
        )
    if not isinstance(list_href, str) or not list_href.startswith("/"):
        raise TodoSyncServiceError(
            "SYNC_INPUT_INVALID", "所选清单不合法", status_code=422
        )
    if len(list_href) > 2048 or ".." in list_href.split("/") or "\\" in list_href:
        raise TodoSyncServiceError(
            "SYNC_INPUT_INVALID", "所选清单不合法", status_code=422
        )
    profile_id = _profile_id(session)
    row = _setting_row(session, profile_id)
    _require_setting_account(row, runtime)
    account = _account(runtime)
    client = _client(runtime, account)
    fingerprint = _fingerprint("select", {"href": list_href})
    replay = _replay(session, profile_id, rid, "select", fingerprint)
    if replay is not None:
        return replay
    try:
        probe = client.probe_connection()
        home = client.calendar_home(probe.get("principal"))
        lists = client.list_lists(home)
    except CalDAVError as exc:
        raise TodoSyncServiceError(exc.code, exc.message, status_code=502) from exc
    chosen = next((item for item in lists if item.href == list_href), None)
    if chosen is None:
        raise TodoSyncServiceError(
            "SYNC_LIST_NOT_FOUND", "所选清单不存在，请刷新后重新选择", status_code=409
        )
    if chosen.supports_vtodo is False:
        # The server explicitly confirmed (200 propstat, no VTODO component)
        # that this calendar cannot hold tasks: refuse instead of enabling a
        # linkage that can never sync.
        raise TodoSyncServiceError(
            "SYNC_LIST_UNSUPPORTED",
            "所选清单不支持任务（VTODO），请选择支持任务的清单",
            status_code=409,
        )
    begin_immediate(session)
    try:
        row = _setting_row(session, profile_id)
        if row is None:
            raise TodoSyncServiceError(
                "SYNC_NOT_CONNECTED", "尚未连接 Nextcloud", status_code=409
            )
        if int(row.setting_version) != expected_version:
            raise TodoSyncServiceError(
                "SYNC_VERSION_CONFLICT", "同步设置已在其他窗口更新", status_code=409
            )
        row.list_href = chosen.href
        row.list_name = chosen.display_name
        row.enabled = True
        row.setting_version = expected_version + 1
        row.updated_at = utc_now()
        result = {
            "ok": True,
            "enabled": True,
            "list_href": chosen.href,
            "list_name": chosen.display_name,
            "setting_version": expected_version + 1,
        }
        _insert_receipt(session, profile_id, rid, "select", fingerprint, result)
        session.commit()
    except BaseException:
        _safe_rollback(session)
        raise
    return result


def disable(
    session: Session,
    runtime,
    *,
    request_id: object,
    expected_version: object,
    clear_credentials: object = False,
) -> dict[str, Any]:
    """Stop the linkage (and optionally forget the machine-local account)."""
    rid = normalize_request_id(request_id)
    if not isinstance(expected_version, int):
        raise TodoSyncServiceError(
            "SYNC_INPUT_INVALID", "设置版本必须是整数", status_code=422
        )
    profile_id = _profile_id(session)
    fingerprint = _fingerprint(
        "disable", {"clear_credentials": clear_credentials is True}
    )
    replay = _replay(session, profile_id, rid, "disable", fingerprint)
    if replay is not None:
        return replay
    begin_immediate(session)
    try:
        row = _setting_row(session, profile_id)
        if row is None:
            raise TodoSyncServiceError(
                "SYNC_NOT_CONNECTED", "尚未连接 Nextcloud", status_code=409
            )
        if int(row.setting_version) != expected_version:
            raise TodoSyncServiceError(
                "SYNC_VERSION_CONFLICT", "同步设置已在其他窗口更新", status_code=409
            )
        row.enabled = False
        row.setting_version = expected_version + 1
        row.updated_at = utc_now()
        result = {
            "ok": True,
            "enabled": False,
            "setting_version": expected_version + 1,
            "credentials_cleared": clear_credentials is True,
        }
        _insert_receipt(session, profile_id, rid, "disable", fingerprint, result)
        session.commit()
    except BaseException:
        _safe_rollback(session)
        raise
    if clear_credentials is True:
        try:
            _store(runtime).clear()
        except TodoSyncCredentialError as exc:
            raise TodoSyncServiceError(
                exc.code, exc.message, status_code=409
            ) from exc
    return result


# ---------------------------------------------------------------------------
# The two-way engine
# ---------------------------------------------------------------------------


def _binding_current(session: Session, profile_id: str, scope: dict) -> bool:
    """True only when the live binding still matches this run's scope.

    The scope is pinned when the engine starts (setting_version + the exact
    account/list triple).  A concurrent connect/select/disable bumps the
    version: an in-flight run must then stop before its next network write
    instead of pushing to the previous account's list.  The re-read expires
    the session cache so a stale identity-map snapshot can never satisfy
    the guard.
    """
    session.expire_all()
    with read_scope(session):
        row = _setting_row(session, profile_id)
    if row is None or not row.enabled:
        return False
    return (
        int(row.setting_version) == int(scope["setting_version"])
        and row.server_url == scope["server_url"]
        and row.username == scope["username"]
        and row.list_href == scope["list_href"]
    )


def _adopt_lost_create(
    session: Session,
    repo,
    profile_id: str,
    task,
    remote_state: str,
    links_by_uid: dict,
    links_by_todo: dict,
    foreign_todo_ids: set[str],
    scope: dict,
):
    """Adopt a remote task onto its deterministic local todo, if any.

    A create PUT whose reply was lost (or a crash between the remote write
    and the local link commit) leaves the remote task named after a local
    todo that has no link yet.  Adoption never decides content:

    - identical content (the usual lost-reply case): only the link is
      claimed, with ``pushed_state`` = the remote state.  The local todo is
      untouched — in particular its version does not move, so the current
      editor keeps working.
    - differing content (another client edited the task since our PUT):
      there is no known baseline, so neither side may win.  No link is
      created; the caller reports a conflict and both sides are kept until
      the teacher resolves it.

    A local todo linked to another account/list (foreign) is skipped: that
    remote task belongs to the current account and imports as an
    independent local todo.
    """
    todo_id = _local_todo_id_from_uid(task.uid)
    if todo_id is None:
        return None
    if todo_id in foreign_todo_ids:
        return None
    local = repo.get_todo(todo_id)
    if local is None:
        return None
    if links_by_todo.get(todo_id) is not None:
        return None
    if _todo_state(local) != remote_state:
        # No baseline: keep both sides, surface a conflict.
        return None
    now = utc_now()
    begin_immediate(session)
    try:
        existing = session.get(LocalTodoSyncLink, (profile_id, todo_id))
        if existing is not None:
            session.commit()
            return existing
        link = LocalTodoSyncLink(
            profile_id=profile_id,
            todo_id=todo_id,
            server_url=scope["server_url"],
            username=scope["username"],
            list_href=scope["list_href"],
            remote_uid=task.uid,
            remote_href=task.href,
            remote_etag=task.etag,
            pushed_state=remote_state,
            remote_missing=False,
            created_at=now,
            updated_at=now,
        )
        session.add(link)
        session.flush()
        session.commit()
    except BaseException:
        _safe_rollback(session)
        raise
    links_by_uid[task.uid] = link
    links_by_todo[todo_id] = link
    return link


def _local_todo_id_from_uid(uid: str) -> str | None:
    """The local todo id inside a deterministic UID, or None."""
    prefix = "kgm-todo-"
    suffix = UID_SUFFIX
    if not isinstance(uid, str) or not uid.startswith(prefix):
        return None
    if not uid.endswith(suffix):
        return None
    todo_id = uid[len(prefix): -len(suffix)]
    # Opaque ids are 22 url-safe characters (A-Z a-z 0-9 - _); accept the
    # full alphabet so a real deterministic UID always parses back.
    if not todo_id or len(todo_id) > 64:
        return None
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in todo_id):
        return None
    return todo_id


def _clean_remote_title(raw: object) -> str:
    """Bound one remote SUMMARY into the local title constraint (1..200)."""
    if not isinstance(raw, str):
        return "无标题任务"
    title = raw.strip()
    if not title:
        # The local title column requires a non-empty value; a remote task
        # without a usable SUMMARY keeps a fixed placeholder instead of
        # failing the pull.
        return "无标题任务"
    if len(title) > MAX_TITLE:
        # An over-long remote summary is stored truncated, never dropped.
        title = title[:MAX_TITLE].rstrip() or "无标题任务"
    return title


def _run_engine(session: Session, runtime) -> dict[str, Any]:
    """One bounded two-way sync run (no receipt; the caller wraps it)."""
    profile_id = _profile_id(session)
    with read_scope(session):
        setting = _setting_row(session, profile_id)
        if setting is None or not setting.enabled or not setting.list_href:
            return {"state": "disabled"}
        # A restored profile whose settings row names another account must
        # never reach the network with this machine's credentials.
        _require_setting_account(setting, runtime)
    account = _account(runtime)
    client = _client(runtime, account)
    list_href = setting.list_href
    # The run's link scope: exactly the account + list this engine talks to,
    # pinned with the setting version so a concurrent connect/select/disable
    # atomically invalidates every later network write of this run.
    scope = {
        "server_url": setting.server_url,
        "username": setting.username,
        "list_href": setting.list_href,
        "setting_version": int(setting.setting_version),
    }
    repo = SqlTodoRepository(session, profile_id)

    counts = {
        "pulled_created": 0,
        "pulled_updated": 0,
        "pushed_created": 0,
        "pushed_updated": 0,
        "reattached": 0,
        "remote_missing": 0,
        "conflicts": 0,
        "remote_kept_local": 0,
    }
    error_codes: list[str] = []
    # Items the pull phase already classified as both-sides-changed; the
    # push phase must skip (not double-count) the same conflict.
    conflicted: set[str] = set()
    # Deterministic pairings the pull phase refused to decide (lost create
    # reply with differing content): the push loop must never claim or
    # create them either, or the second run would overwrite the remote.
    conflicted_todo_ids: set[str] = set()

    # -- one bounded remote listing ------------------------------------
    try:
        remote_tasks = client.list_tasks(list_href)
    except CalDAVError as exc:
        raise TodoSyncServiceError(exc.code, exc.message, status_code=502) from exc
    remote_by_uid: dict[str, Any] = {task.uid: task for task in remote_tasks}

    with read_scope(session):
        all_links = session.scalars(
            select(LocalTodoSyncLink).where(
                LocalTodoSyncLink.profile_id == profile_id
            )
        ).all()
    # Account+list scoping via the real origin binding stored on each link
    # (normalized server origin + username + the full selected list href):
    # two different servers or accounts can serve byte-identical href paths
    # (and `tasks` vs `tasks-next` share a prefix), so href matching alone
    # can never decide scope.  Foreign links are never pulled, never pushed,
    # never marked remotely missing, and they never block importing this
    # account's independent same-UID task.
    links = [
        link
        for link in all_links
        if link.server_url == setting.server_url
        and link.username == setting.username
        and link.list_href == setting.list_href
    ]
    foreign_todo_ids = {
        link.todo_id
        for link in all_links
        if link not in links
    }
    links_by_uid = {link.remote_uid: link for link in links}
    links_by_todo = {link.todo_id: link for link in links}

    # -- pull: remote creates/edits/completions -----------------------
    for task in remote_tasks:
        link = links_by_uid.get(task.uid)
        remote_state = state_hash(
            _clean_remote_title(task.title), task.due_date, task.completed
        )
        if link is None:
            # A previous create whose reply was lost (or a crash between the
            # remote PUT and the local link write) leaves the remote task
            # carrying this local todo's deterministic UID without a link.
            # Adopt it onto the existing local todo instead of creating a
            # second one (1 remote must never become 2 local).  A todo whose
            # link belongs to another account/list is foreign: its task
            # never adopts here — the new account's task imports as an
            # independent local todo instead.
            adopted = _adopt_lost_create(
                session,
                repo,
                profile_id,
                task,
                remote_state,
                links_by_uid,
                links_by_todo,
                foreign_todo_ids,
                scope,
            )
            if adopted is not None:
                counts["reattached"] += 1
                continue
            if (
                _local_todo_id_from_uid(task.uid) is not None
                and repo.get_todo(_local_todo_id_from_uid(task.uid)) is not None
                and _local_todo_id_from_uid(task.uid)
                not in foreign_todo_ids
            ):
                # The deterministic local todo exists but its content
                # differs from the remote task: without a baseline neither
                # side wins.  Keep both and surface the conflict; the push
                # loop skips this todo entirely (no claim, no create).
                conflicted_todo_ids.add(_local_todo_id_from_uid(task.uid))
                counts["conflicts"] += 1
                continue
            title = _clean_remote_title(task.title)
            now = utc_now()
            todo_id = new_opaque_id()
            begin_immediate(session)
            try:
                session.add(
                    _new_todo_row(
                        profile_id,
                        todo_id,
                        title,
                        _as_date(task.due_date),
                        task.completed,
                        now,
                    )
                )
                session.add(
                    LocalTodoSyncLink(
                        profile_id=profile_id,
                        todo_id=todo_id,
                        server_url=scope["server_url"],
                        username=scope["username"],
                        list_href=scope["list_href"],
                        remote_uid=task.uid,
                        remote_href=task.href,
                        remote_etag=task.etag,
                        pushed_state=remote_state,
                        remote_missing=False,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()
                session.commit()
            except BaseException:
                _safe_rollback(session)
                raise
            links_by_uid[task.uid] = session.get(LocalTodoSyncLink, (profile_id, todo_id))
            links_by_todo[todo_id] = links_by_uid[task.uid]
            counts["pulled_created"] += 1
            continue
        if link.remote_missing:
            # The task reappeared remotely — after a remote delete, or under
            # the newly connected account after an account switch.  Re-attach
            # first; then, when the local todo is unmodified since the last
            # sync, import the remote content (the second account's
            # independent same-UID task is a real remote change and must be
            # pulled).  A locally edited todo is a both-sides conflict: keep
            # the local content, never push it back.
            begin_immediate(session)
            try:
                fresh = session.get(LocalTodoSyncLink, (profile_id, link.todo_id))
                local = repo.get_todo(link.todo_id) if fresh is not None else None
                if fresh is None:
                    session.commit()
                    continue
                if local is None:
                    # The local todo was deleted while detached: drop the
                    # link only (the remote task is untouched).
                    session.delete(fresh)
                    session.commit()
                    counts["remote_kept_local"] += 1
                    continue
                fresh.remote_missing = False
                fresh.remote_href = task.href
                fresh.remote_etag = task.etag
                if _todo_state(local) == (fresh.pushed_state or ""):
                    repo.update_todo(
                        link.todo_id,
                        {
                            "title": _clean_remote_title(task.title),
                            "due_date": _as_date(task.due_date),
                            "completed": bool(task.completed),
                            "version": int(local["version"]) + 1,
                            "updated_at": utc_now(),
                        },
                    )
                    fresh.pushed_state = remote_state
                    fresh.updated_at = utc_now()
                    session.commit()
                    counts["pulled_updated"] += 1
                else:
                    fresh.pushed_state = _todo_state(local)
                    fresh.updated_at = utc_now()
                    session.commit()
                    conflicted.add(link.todo_id)
                    counts["conflicts"] += 1
            except BaseException:
                _safe_rollback(session)
                raise
            continue
        if task.etag == link.remote_etag:
            continue
        with read_scope(session):
            local = repo.get_todo(link.todo_id)
        if local is None:
            # The local todo was deleted while the link survived: drop the
            # link only (the remote task is untouched — deletes are never
            # propagated).
            begin_immediate(session)
            try:
                fresh = session.get(LocalTodoSyncLink, (profile_id, link.todo_id))
                if fresh is not None:
                    session.delete(fresh)
                session.commit()
            except BaseException:
                _safe_rollback(session)
                raise
            counts["remote_kept_local"] += 1
            continue
        if _todo_state(local) != (link.pushed_state or ""):
            # Both sides changed: never overwrite, report the conflict once.
            counts["conflicts"] += 1
            conflicted.add(link.todo_id)
            continue
        begin_immediate(session)
        try:
            fresh_link = session.get(LocalTodoSyncLink, (profile_id, link.todo_id))
            fresh_todo = repo.get_todo(link.todo_id)
            if (
                fresh_link is None
                or fresh_todo is None
                or _todo_state(fresh_todo) != (fresh_link.pushed_state or "")
            ):
                session.commit()
                continue
            repo.update_todo(
                link.todo_id,
                {
                    "title": _clean_remote_title(task.title),
                    "due_date": _as_date(task.due_date),
                    "completed": bool(task.completed),
                    "version": int(fresh_todo["version"]) + 1,
                    "updated_at": utc_now(),
                },
            )
            fresh_link.remote_href = task.href
            fresh_link.remote_etag = task.etag
            fresh_link.pushed_state = remote_state
            fresh_link.updated_at = utc_now()
            session.commit()
            counts["pulled_updated"] += 1
        except BaseException:
            _safe_rollback(session)
            raise

    # -- remote deletes are never propagated ---------------------------
    for link in links:
        if link.remote_uid in remote_by_uid or link.remote_missing:
            continue
        begin_immediate(session)
        try:
            fresh = session.get(LocalTodoSyncLink, (profile_id, link.todo_id))
            if fresh is not None and not fresh.remote_missing:
                fresh.remote_missing = True
                fresh.updated_at = utc_now()
            session.commit()
        except BaseException:
            _safe_rollback(session)
            raise
        counts["remote_missing"] += 1

    # -- push: local creates/edits/completions ------------------------
    # ``list_todos`` opens its own explicit read scope.
    local_todos = repo.list_todos(archived=False)
    for todo in local_todos:
        if todo["todo_id"] in foreign_todo_ids:
            # This todo's link belongs to another account/list: it is never
            # exported there, and switching back re-attaches it in scope.
            continue
        if todo["todo_id"] in conflicted_todo_ids:
            # The pull phase refused to pair this todo with its
            # deterministic remote task (no baseline, content differs):
            # claiming or creating here would silently overwrite one side.
            continue
        link = links_by_todo.get(todo["todo_id"])
        current_state = _todo_state(todo)
        if link is None:
            uid = deterministic_uid(todo["todo_id"])
            existing = remote_by_uid.get(uid)
            if existing is not None:
                # A previous partial create left the remote task: adopt it
                # instead of duplicating; local differences push next run.
                if not _binding_current(session, profile_id, scope):
                    result = dict(counts)
                    result["state"] = "disabled"
                    return result
                now = utc_now()
                begin_immediate(session)
                try:
                    session.add(
                        LocalTodoSyncLink(
                            profile_id=profile_id,
                            todo_id=todo["todo_id"],
                            server_url=scope["server_url"],
                            username=scope["username"],
                            list_href=scope["list_href"],
                            remote_uid=uid,
                            remote_href=existing.href,
                            remote_etag=existing.etag,
                            pushed_state=state_hash(
                                _clean_remote_title(existing.title),
                                existing.due_date,
                                existing.completed,
                            ),
                            remote_missing=False,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    session.flush()
                    session.commit()
                except BaseException:
                    _safe_rollback(session)
                    raise
                counts["reattached"] += 1
                continue
            ical = _vtodo_for(uid, todo)
            if not _binding_current(session, profile_id, scope):
                result = dict(counts)
                result["state"] = "disabled"
                return result
            try:
                new_etag = client.put_task(
                    f"{list_href.rstrip('/')}/{uid}.ics", ical, etag=None
                )
            except CalDAVError as exc:
                error_codes.append(exc.code)
                continue
            now = utc_now()
            begin_immediate(session)
            try:
                session.add(
                    LocalTodoSyncLink(
                        profile_id=profile_id,
                        todo_id=todo["todo_id"],
                        server_url=scope["server_url"],
                        username=scope["username"],
                        list_href=scope["list_href"],
                        remote_uid=uid,
                        remote_href=f"{list_href.rstrip('/')}/{uid}.ics",
                        remote_etag=new_etag,
                        pushed_state=current_state,
                        remote_missing=False,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()
                session.commit()
            except BaseException:
                _safe_rollback(session)
                raise
            counts["pushed_created"] += 1
            continue
        if link.remote_missing:
            # The remote task was deleted remotely: the local todo is kept
            # and never pushed back.
            continue
        if todo["todo_id"] in conflicted:
            # Already classified as a both-sides conflict in the pull
            # phase: skip without counting it twice.
            continue
        if current_state == (link.pushed_state or ""):
            continue
        existing = remote_by_uid.get(link.remote_uid)
        if existing is None:
            # Vanished between the listing and now: treated as remotely
            # missing; the local copy stays untouched.
            begin_immediate(session)
            try:
                fresh = session.get(LocalTodoSyncLink, (profile_id, todo["todo_id"]))
                if fresh is not None and not fresh.remote_missing:
                    fresh.remote_missing = True
                    fresh.updated_at = utc_now()
                session.commit()
            except BaseException:
                _safe_rollback(session)
                raise
            counts["remote_missing"] += 1
            continue
        if existing.etag != (link.remote_etag or ""):
            # Both sides changed since the last sync: skip, never overwrite.
            counts["conflicts"] += 1
            continue
        if not _binding_current(session, profile_id, scope):
            result = dict(counts)
            result["state"] = "disabled"
            return result
        if not (existing.raw_calendar or "").strip():
            # Editing without the remote's real calendar data would delete
            # fields the local model does not carry; refuse instead.
            error_codes.append("SYNC_RESPONSE_INVALID")
            continue
        if not _binding_current(session, profile_id, scope):
            result = dict(counts)
            result["state"] = "disabled"
            return result
        from app.local.todo_sync_caldav import TodoSyncError as _CalDAVError
        from app.local.todo_sync_merge import merge_vtodo

        try:
            ical = merge_vtodo(
                existing.raw_calendar,
                uid=link.remote_uid,
                title=str(todo["title"]),
                due_date=(
                    todo["due_date"].isoformat()
                    if hasattr(todo.get("due_date"), "isoformat")
                    else todo.get("due_date")
                ),
                completed=bool(todo["completed"]),
            )
        except _CalDAVError as exc:
            error_codes.append(exc.code)
            continue
        try:
            new_etag = client.put_task(
                link.remote_href, ical, etag=link.remote_etag
            )
        except CalDAVError as exc:
            if exc.code == "SYNC_PRECONDITION_FAILED":
                counts["conflicts"] += 1
            else:
                error_codes.append(exc.code)
            continue
        begin_immediate(session)
        try:
            fresh_link = session.get(LocalTodoSyncLink, (profile_id, todo["todo_id"]))
            fresh_todo = repo.get_todo(todo["todo_id"])
            if (
                fresh_link is None
                or fresh_todo is None
                or _todo_state(fresh_todo) != current_state
            ):
                # The teacher edited during the PUT: keep the link as-is so
                # the next run re-evaluates instead of masking the edit.
                session.commit()
                continue
            fresh_link.remote_etag = new_etag
            fresh_link.pushed_state = current_state
            fresh_link.updated_at = utc_now()
            session.commit()
            counts["pushed_updated"] += 1
        except BaseException:
            _safe_rollback(session)
            raise

    result = dict(counts)
    result["state"] = "ok" if not error_codes else "partial"
    result["error_codes"] = sorted(set(error_codes))
    return result


def _vtodo_for(uid: str, todo: dict[str, Any]) -> bytes:
    from app.local.todo_sync_caldav import build_vtodo

    due = todo["due_date"]
    if hasattr(due, "isoformat"):
        # The local repository carries a ``datetime.date``; the iCalendar
        # payload always uses the plain ``YYYY-MM-DD`` text form.
        due = due.isoformat()
    return build_vtodo(
        uid=uid,
        title=str(todo["title"]),
        due_date=due,
        completed=bool(todo["completed"]),
    )


def _as_date(value: str | None):
    """Convert one remote ``YYYY-MM-DD`` string into a ``date`` object."""
    from datetime import date as _date

    if value is None or value == "":
        return None
    try:
        return _date.fromisoformat(str(value))
    except ValueError:
        return None


def _new_todo_row(profile_id, todo_id, title, due_date, completed, now):
    from app.local.todo_models import LocalTodo

    return LocalTodo(
        id=todo_id,
        profile_id=profile_id,
        title=title,
        due_date=due_date,
        completed=bool(completed),
        version=1,
        created_at=now,
        updated_at=now,
    )


def _persist_result(session: Session, profile_id: str, result: dict[str, Any]) -> None:
    begin_immediate(session)
    try:
        row = _setting_row(session, profile_id)
        if row is None:
            session.commit()
            return
        row.last_sync_at = utc_now()
        row.last_result = result
        row.updated_at = utc_now()
        session.commit()
    except BaseException:
        _safe_rollback(session)
        raise


def run_sync(session: Session, runtime, *, request_id: object = None) -> dict[str, Any]:
    """Run one bounded sync now.

    With ``request_id`` the outcome is an idempotent receipt; background
    runs pass ``None`` and simply execute once.  Manual and background runs
    share the engine mutex: a run that starts while another engine is
    mid-flight waits for it, so two engines can never process the same
    task (the receipt re-read happens inside the lock, so a request that
    waited still replays the committed receipt instead of re-running).
    """
    rid = normalize_request_id(request_id) if request_id is not None else None
    profile_id = _profile_id(session)
    fingerprint = _fingerprint("sync", {})
    with _engine_lock:
        if rid is not None:
            replay = _replay(session, profile_id, rid, "sync", fingerprint)
            if replay is not None:
                return replay
        result = _run_engine(session, runtime)
        if result.get("state") != "disabled":
            _persist_result(session, profile_id, result)
        if rid is not None:
            begin_immediate(session)
            try:
                _insert_receipt(session, profile_id, rid, "sync", fingerprint, result)
                session.commit()
            except BaseException:
                _safe_rollback(session)
                raise
    return result


# ---------------------------------------------------------------------------
# Background single-flight scheduling
# ---------------------------------------------------------------------------


def schedule_background_sync(runtime) -> None:
    """Best-effort coalesced sync after a local todo write; never blocks.

    The linkage stops the moment the setting is disabled: the thread checks
    ``enabled`` itself and exits without scheduling anything further.  The
    single-flight gate is always released by the worker's ``finally``, so a
    disabled run can never lock out a later re-enable.
    """
    global _sync_in_flight, _sync_pending
    if runtime is None:
        return
    with _sync_gate:
        if _sync_in_flight:
            _sync_pending = True
            return
        _sync_in_flight = True
        _sync_pending = False
    thread = threading.Thread(
        target=_background_worker,
        args=(runtime,),
        name=f"todo-sync-{secrets.token_hex(4)}",
        daemon=True,
    )
    thread.start()


def _background_worker(runtime) -> None:
    global _sync_in_flight, _sync_pending
    try:
        while True:
            session = runtime.session()
            try:
                with read_scope(session):
                    setting = _setting_row(
                        session,
                        _profile_id(session),
                    )
                    enabled = setting is not None and bool(setting.enabled)
                if not enabled:
                    return
                try:
                    run_sync(session, runtime)
                except Exception:  # noqa: BLE001 - background best effort
                    return
            finally:
                session.close()
            with _sync_gate:
                if not _sync_pending:
                    return
                _sync_pending = False
    finally:
        # Every exit path (disabled, failure, completion) releases the
        # single-flight gate: a disabled worker must never leave the gate
        # locked against a later re-enable.
        with _sync_gate:
            _sync_in_flight = False
            _sync_pending = False


__all__ = [
    "TodoSyncServiceError",
    "connect_account",
    "deterministic_uid",
    "disable",
    "get_status",
    "list_lists",
    "run_sync",
    "schedule_background_sync",
    "select_list",
    "state_hash",
]
