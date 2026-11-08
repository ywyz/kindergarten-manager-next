"""Prompt package check, enable, cache and status service.

Network work happens outside any database transaction.  The fixed HTTPS source
comes from :mod:`app.local.prompt_package`; this service never accepts a URL or
key from a request.  A successful package is staged to a file, registered
through the existing ``local_prompt_bundles`` sync path, then marked active and
recorded in the accepted-sequence ledger.  Any failure leaves the last active
package in place; if no verified cache remains, untouched default-only heads
are really returned to the built-in default while history and in-flight pins
stay intact.

The service is intentionally importable without a database.  Pure tests inject
``apply_func`` and ``fetcher``; the production path uses ``runtime.session()``
only inside ``_apply``.
"""

from __future__ import annotations

import hashlib
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from app.local.errors import (
    LocalPromptBundleConflict,
    LocalPromptContractRegression,
    LocalValidationError,
)
from app.local.prompt_package import (
    MAX_PACKAGE_BYTES,
    PACKAGE_OPEN_TASK_TYPES,
    PACKAGE_TASK_TYPES,
    PackageTrust,
    PromptPackageError,
    VerifiedPackage,
    materialize_bundle_rows,
    packaged_trust,
    verify_package,
)
from app.local.prompt_package_manifest import (
    MAX_MANIFEST_BYTES,
    PromptManifest,
    manifest_url,
    package_url,
    verify_manifest,
    verify_package_for_manifest,
)
from app.local.prompt_package_store import PromptPackageStore
from app.local.tx import read_scope

DEFAULT_BACKGROUND_INTERVAL_SECONDS = 6 * 60 * 60
NETWORK_TIMEOUT_SECONDS = 15

Result = dict[str, Any]


class PromptPackageNetworkError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise PromptPackageNetworkError(
            "PACKAGE_REDIRECT_REFUSED", "提示词包来源重定向被拒绝"
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _positive_int(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1
        else None
    )


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _fetch_https(
    url: str,
    *,
    no_cache: bool,
    max_bytes: int,
    timeout: float,
) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PromptPackageNetworkError(
            "PACKAGE_SOURCE_INVALID", "提示词包来源必须是固定 HTTPS 地址"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise PromptPackageNetworkError(
            "PACKAGE_SOURCE_INVALID", "提示词包来源格式无效"
        )
    headers = {
        "Accept": "application/json",
        "User-Agent": "kindergarten-manager-prompt-package/1",
    }
    if no_cache:
        headers["Cache-Control"] = "no-cache"
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status != 200:
                raise PromptPackageNetworkError(
                    "PACKAGE_HTTP_STATUS", "提示词包来源返回异常状态"
                )
            content_type = response.headers.get("Content-Type", "")
            if content_type and "json" not in content_type.lower():
                raise PromptPackageNetworkError(
                    "PACKAGE_CONTENT_TYPE", "提示词包来源未返回 JSON"
                )
            data = response.read(max_bytes + 1)
    except PromptPackageNetworkError:
        raise
    except urllib.error.HTTPError as exc:
        raise PromptPackageNetworkError(
            "PACKAGE_HTTP_STATUS", f"提示词包来源返回 HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        message = "无法连接提示词包来源"
        if isinstance(reason, OSError) and "certificate" in str(reason).lower():
            message = "提示词包来源 TLS 证书校验失败"
        raise PromptPackageNetworkError("PACKAGE_OFFLINE", message) from exc
    except (TimeoutError, OSError) as exc:
        raise PromptPackageNetworkError(
            "PACKAGE_OFFLINE", "连接提示词包来源超时或中断"
        ) from exc
    if len(data) > max_bytes:
        raise PromptPackageNetworkError(
            "PACKAGE_TOO_LARGE", "提示词包超过大小上限"
        )
    if not data:
        raise PromptPackageNetworkError(
            "PACKAGE_EMPTY", "提示词包来源返回空内容"
        )
    return data


def fetch_signed_package(
    trust: PackageTrust,
    *,
    timeout: float = NETWORK_TIMEOUT_SECONDS,
    max_bytes: int = MAX_PACKAGE_BYTES,
) -> bytes:
    """Legacy direct signed-package URL, retained for compatibility."""
    if not trust.configured or not trust.source_url:
        raise PromptPackageNetworkError(
            "PACKAGE_SOURCE_UNCONFIGURED", "提示词包来源未配置"
        )
    return _fetch_https(
        trust.source_url,
        no_cache=True,
        max_bytes=max_bytes,
        timeout=timeout,
    )


def fetch_signed_manifest(
    trust: PackageTrust,
    *,
    timeout: float = NETWORK_TIMEOUT_SECONDS,
    max_bytes: int = MAX_MANIFEST_BYTES,
) -> bytes:
    """Fetch a channel latest manifest with an explicit no-cache request."""
    if not trust.configured:
        raise PromptPackageNetworkError(
            "PACKAGE_SOURCE_UNCONFIGURED", "提示词包来源未配置"
        )
    try:
        url = manifest_url(trust)
    except PromptPackageError as exc:
        raise PromptPackageNetworkError(exc.code, exc.message) from None
    return _fetch_https(
        url,
        no_cache=True,
        max_bytes=max_bytes,
        timeout=timeout,
    )


def fetch_channel_package(
    trust: PackageTrust,
    manifest: PromptManifest,
    *,
    timeout: float = NETWORK_TIMEOUT_SECONDS,
    max_bytes: int = MAX_PACKAGE_BYTES,
) -> bytes:
    """Fetch one immutable version file, allowing normal HTTP caching."""
    if not trust.configured:
        raise PromptPackageNetworkError(
            "PACKAGE_SOURCE_UNCONFIGURED", "提示词包来源未配置"
        )
    try:
        url = package_url(trust, manifest)
    except PromptPackageError as exc:
        raise PromptPackageNetworkError(exc.code, exc.message) from None
    return _fetch_https(
        url,
        no_cache=False,
        max_bytes=max_bytes,
        timeout=timeout,
    )

class PromptPackageService:
    def __init__(
        self,
        runtime: Any,
        *,
        trust: PackageTrust | None = None,
        store: PromptPackageStore | None = None,
        fetcher: Callable[[PackageTrust], bytes] | None = None,
        manifest_fetcher: Callable[[PackageTrust], bytes] | None = None,
        channel_package_fetcher: (
            Callable[[PackageTrust, PromptManifest], bytes] | None
        ) = None,
        apply_func: Callable[[VerifiedPackage], None] | None = None,
        fallback_func: Callable[[str], None] | None = None,
        client_version: str | None = None,
        background_interval_seconds: int = DEFAULT_BACKGROUND_INTERVAL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ):
        self.runtime = runtime
        # Until startup verifies a cache, a new profile must use built-in
        # defaults rather than historical remote rows.
        self.runtime.prompt_package_builtin_only = True
        self.trust = trust or packaged_trust()
        if client_version is not None:
            self.trust = PackageTrust(
                source_url=self.trust.source_url,
                keys=dict(self.trust.keys),
                client_version=client_version,
                channel=self.trust.channel,
            )
        root = getattr(runtime, "data_dir", None)
        if store is not None:
            self.store = store
        elif self.trust.channel in ("preview", "stable"):
            base = Path(root) if root is not None else Path(".")
            self.store = PromptPackageStore(
                base / ".prompt-packages", channel=self.trust.channel
            )
        else:
            self.store = PromptPackageStore(
                Path(root) if root is not None else Path(".prompt-packages")
            )
        self._fetcher = fetcher or fetch_signed_package
        self._manifest_fetcher = manifest_fetcher or fetch_signed_manifest
        self._channel_package_fetcher = (
            channel_package_fetcher or fetch_channel_package
        )
        self._apply_func = apply_func
        self._fallback_func = fallback_func
        self._now = now or _utc_now
        self.background_interval_seconds = max(0, int(background_interval_seconds))
        self._lock = threading.Lock()
        self._checking = False
        self._background_started = False
        # Disk cache verification is not the same as this runtime having
        # successfully registered the package in the database.
        self._activated_content_sha256: str | None = None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def _prompt_sync_error(self) -> str | None:
        return getattr(self.runtime, "prompt_sync_error", None)

    def _verify_cached_manifest(
        self,
        raw: bytes,
        package: VerifiedPackage,
        manifest_raw: bytes | None,
        metadata: Any,
    ) -> tuple[PromptManifest | None, str | None]:
        """Require the signed manifest that admitted a channel cache package.

        The directory name and the unsigned ``channel`` metadata field are not
        proof.  A channel cache is usable offline only when its stored raw
        manifest still verifies against the fixed trust, its digest matches the
        state entry, and it binds this exact package (channel, sequence, raw
        SHA-256 and key).  Legacy direct-package caches have no channel and keep
        their previous behavior.
        """
        if self.trust.channel is None:
            return None, None
        if manifest_raw is None:
            return None, "PACKAGE_MANIFEST_PROOF_MISSING"
        if (
            not isinstance(metadata, dict)
            or metadata.get("manifest_sha256")
            != hashlib.sha256(manifest_raw).hexdigest()
        ):
            return None, "PACKAGE_MANIFEST_PROOF_MISMATCH"
        try:
            manifest = verify_manifest(manifest_raw, self.trust)
            verify_package_for_manifest(
                raw,
                manifest,
                self.trust,
                client_version=self.trust.client_version,
            )
        except PromptPackageError as exc:
            return None, exc.code
        if (
            metadata.get("channel") != manifest.channel
            or metadata.get("release_sequence") != manifest.release_sequence
            or metadata.get("raw_sha256") != manifest.package_sha256
            or metadata.get("key_id") != manifest.key_id
        ):
            return None, "PACKAGE_CACHE_MISMATCH"
        return manifest, None

    def _active_cache(
        self, active: Any
    ) -> tuple[VerifiedPackage | None, str | None]:
        """Verify the active cache file and match it to the ledger metadata."""
        if not isinstance(active, dict):
            return None, None
        raw = self.store.load_active_raw()
        if raw is None:
            return None, "missing"
        try:
            package = verify_package(
                raw, self.trust, client_version=self.trust.client_version
            )
        except PromptPackageError as exc:
            return None, exc.code
        _manifest, proof_error = self._verify_cached_manifest(
            raw,
            package,
            self.store.load_active_manifest(),
            active,
        )
        if proof_error is not None:
            return None, proof_error
        if (
            active.get("channel") != self.trust.channel
            or active.get("release_sequence") != package.release_sequence
            or active.get("content_sha256") != package.content_sha256
            or active.get("raw_sha256") != package.raw_sha256
        ):
            return None, "PACKAGE_CACHE_MISMATCH"
        return package, None

    def _ensure_builtin_fallback(self, reason: str) -> None:
        """Make the documented built-in fallback real for not-started work."""
        self.runtime.prompt_package_builtin_only = True
        if self._fallback_func is not None:
            try:
                self._fallback_func(reason)
            except Exception:  # noqa: BLE001 - fallback is best-effort
                pass
            return
        session_factory = getattr(self.runtime, "session", None)
        if not callable(session_factory):
            return
        session = None
        try:
            from app.local.prompt_bundles import (
                revert_default_only_to_builtin,
            )

            session = session_factory()
            revert_default_only_to_builtin(
                session, task_types=PACKAGE_TASK_TYPES
            )
        except Exception:  # noqa: BLE001 - never block manual or startup paths
            pass
        finally:
            if session is not None:
                session.close()

    def _fallback_if_no_valid_cache(self, reason: str) -> None:
        state = self.store.read_state()
        active = state.get("active")
        if isinstance(active, dict):
            package, _error = self._active_cache(active)
            if package is not None:
                return
        self._ensure_builtin_fallback(reason)

    def status(self) -> Result:
        state = self.store.read_state()
        active = state.get("active")
        pending = state.get("pending")
        last = state.get("last_check") or {}
        configured = self.trust.configured
        active_package: VerifiedPackage | None = None
        active_cache_error: str | None = None
        if configured:
            active_package, active_cache_error = self._active_cache(active)
        active_source = "package" if active_package is not None else "builtin"
        sequence = (
            _positive_int(active.get("release_sequence"))
            if isinstance(active, dict)
            else None
        )
        failure_results = {
            "rollback_rejected",
            "sequence_conflict",
            "identity_conflict",
            "offline",
            "invalid",
            "incompatible",
            "rejected",
            "failed",
        }
        last_result = last.get("result") if isinstance(last, dict) else None
        if not configured:
            lifecycle = "unconfigured"
            message = "提示词包来源未配置；当前使用程序内置文字。"
        elif self._checking:
            lifecycle = "checking"
            message = "正在检查提示词更新…"
        elif last_result in failure_results:
            lifecycle = str(last_result)
            message = str(last.get("message") or "")
        elif active_cache_error == "missing":
            lifecycle = "cache_missing"
            label = f"r{sequence}" if sequence is not None else "发布序号"
            message = (
                f"已接受的{label}缺少可用缓存；"
                "当前使用程序已登记文字或内置文字，可手动检查修复。"
            )
        elif active_cache_error is not None:
            lifecycle = "cache_invalid"
            message = (
                "本地功能包缓存校验失败或与账本不一致；"
                "当前使用程序已登记文字或内置文字，可手动检查修复。"
            )
        elif active_package is not None and last_result in (
            "cache_invalid",
            "cache_stale",
            "cache_reused",
        ):
            lifecycle = "package"
            message = f"当前使用已验证功能包 r{sequence}。"
        elif isinstance(last, dict) and last.get("result"):
            lifecycle = str(last.get("result"))
            message = str(last.get("message") or "")
        elif active_package is not None:
            lifecycle = "package"
            message = f"当前使用已验证功能包 r{sequence}。"
        else:
            lifecycle = "builtin"
            message = "当前使用程序内置文字。"
        return {
            "configured": configured,
            "state": lifecycle,
            "active_source": active_source,
            "release_sequence": sequence,
            "published_at": (
                active_package.published_at
                if active_package is not None
                else None
            ),
            "notes": (
                active_package.notes
                if active_package is not None
                else None
            ),
            "last_checked_at": (
                _optional_text(last.get("checked_at"))
                if isinstance(last, dict)
                else None
            ),
            "last_result": (
                _optional_text(last.get("result"))
                if isinstance(last, dict)
                else None
            ),
            "message": message,
            "allowed_tasks": list(PACKAGE_OPEN_TASK_TYPES),
            "package_tasks": (
                [
                    {
                        "task_type": item.get("task_type"),
                        "contract_version": item.get("contract_version"),
                        "default_revision": item.get("default_revision"),
                    }
                    for item in active.get("bundles") or []
                    if isinstance(item, dict)
                    and isinstance(item.get("task_type"), str)
                    and _positive_int(item.get("contract_version")) is not None
                    and _positive_int(item.get("default_revision")) is not None
                ]
                if active_package is not None and isinstance(active, dict)
                else []
            ),
            "pending_sequence": (
                _positive_int(pending.get("release_sequence"))
                if isinstance(pending, dict)
                else None
            ),
            "client_version": self.trust.client_version,
            "prompt_sync_error": self._prompt_sync_error(),
        }

    # ------------------------------------------------------------------
    # Check / enable
    # ------------------------------------------------------------------
    def _record(
        self,
        result: str,
        message: str,
        *,
        package: VerifiedPackage | None = None,
        error_code: str | None = None,
    ) -> None:
        self.store.record_check(
            {
                "checked_at": _iso(self._now()),
                "result": result,
                "message": message,
                "release_sequence": (
                    package.release_sequence if package is not None else None
                ),
                "error_code": error_code,
            }
        )

    @staticmethod
    def _result_for_error(error: PromptPackageError) -> str:
        if error.code == "PACKAGE_INCOMPATIBLE" or error.code.startswith(
            "PACKAGE_CONTRACT_INCOMPATIBLE"
        ):
            return "incompatible"
        if error.code in (
            "PACKAGE_DEFAULT_ROLLBACK",
            "PACKAGE_IDENTITY_CONFLICT",
        ):
            return "rollback_rejected"
        if error.code == "PACKAGE_TASK_NOT_ALLOWED":
            return "invalid"
        return "invalid"

    def _apply(self, package: VerifiedPackage) -> None:
        if self._apply_func is not None:
            self._apply_func(package)
            return
        session = self.runtime.session()
        try:
            from sqlalchemy import select

            from app.local.models import LocalPersonalPromptHead
            from app.local.prompt_bundles import sync_prompt_bundles
            from app.local.prompt_package import (
                validate_against_existing_heads,
            )

            with read_scope(session):
                heads = session.scalars(
                    select(LocalPersonalPromptHead).where(
                        LocalPersonalPromptHead.task_type.in_(
                            [bundle.task_type for bundle in package.bundles]
                        )
                    )
                ).all()
                validate_against_existing_heads(
                    package,
                    [
                        (
                            head.task_type,
                            head.required_contract_version,
                            head.latest_default_revision,
                        )
                        for head in heads
                    ],
                )
            rows = materialize_bundle_rows(package)
            sync_prompt_bundles(
                session, rows, auto_advance_defaults=True
            )
        finally:
            session.close()

    def _check_accepted(
        self, package: VerifiedPackage, state: dict[str, Any]
    ) -> str | None:
        accepted = state.get("accepted")
        if not isinstance(accepted, dict):
            return None
        accepted_sequence = accepted.get("release_sequence")
        accepted_hash = accepted.get("content_sha256")
        if not isinstance(accepted_sequence, int):
            return None
        if package.release_sequence < accepted_sequence:
            self._record(
                "rollback_rejected",
                f"已拒绝较低发布序号 r{package.release_sequence}"
                f"（当前已接受 r{accepted_sequence}），不会回放旧包。",
                package=package,
                error_code="PACKAGE_SEQUENCE_ROLLBACK",
            )
            return "rollback_rejected"
        if package.release_sequence == accepted_sequence:
            if accepted_hash == package.content_sha256:
                return "same"
            self._record(
                "sequence_conflict",
                f"发布序号 r{package.release_sequence} 已对应不同内容，已拒绝。",
                package=package,
                error_code="PACKAGE_SEQUENCE_CONFLICT",
            )
            return "sequence_conflict"
        known = accepted.get("bundles")
        if isinstance(known, list):
            by_identity = {
                (
                    item.get("task_type"),
                    item.get("contract_version"),
                    item.get("default_revision"),
                ): item.get("guidance_sha256")
                for item in known
                if isinstance(item, dict)
            }
            for bundle in package.bundles:
                previous = by_identity.get(bundle.identity())
                if (
                    isinstance(previous, str)
                    and previous != bundle.guidance_hash()
                ):
                    self._record(
                        "rejected",
                        "同一任务／契约／默认修订身份对应不同内容，已拒绝。",
                        package=package,
                        error_code="PACKAGE_IDENTITY_CONFLICT",
                    )
                    return "identity_conflict"
        return None

    def check(self, *, manual: bool = True) -> Result:
        if not self.trust.configured:
            # Absolutely no network when unconfigured.
            self._record(
                "unconfigured",
                "提示词包来源未配置；当前使用程序内置文字。",
                error_code="PACKAGE_SOURCE_UNCONFIGURED",
            )
            self._fallback_if_no_valid_cache("unconfigured")
            return self.status()
        if not manual:
            state = self.store.read_state()
            last = state.get("last_check") or {}
            checked = _parse_iso(last.get("checked_at")) if isinstance(last, dict) else None
            network_results = {
                "updated",
                "no_update",
                "offline",
                "invalid",
                "incompatible",
                "rollback_rejected",
                "sequence_conflict",
                "rejected",
            }
            if (
                checked is not None
                and isinstance(last, dict)
                and last.get("result") in network_results
            ):
                elapsed = (self._now() - checked).total_seconds()
                if elapsed < self.background_interval_seconds:
                    return self.status()
        if not self._lock.acquire(blocking=False):
            return self.status()
        self._checking = True
        try:
            self._check_locked()
        finally:
            self._checking = False
            self._lock.release()
        self._fallback_if_no_valid_cache("check_no_valid_cache")
        return self.status()

    def _candidate_package(
        self,
    ) -> tuple[bytes, VerifiedPackage, bytes | None] | None:
        if self.trust.channel in ("preview", "stable"):
            try:
                raw_manifest = self._manifest_fetcher(self.trust)
            except PromptPackageNetworkError as exc:
                self._record(
                    "offline",
                    f"{exc.message}；继续使用已验证版本或内置文字。",
                    error_code=exc.code,
                )
                return None
            except Exception as exc:  # noqa: BLE001 - network never blocks manual work
                self._record(
                    "offline",
                    f"检查提示词更新失败：{exc}；继续使用已验证版本或内置文字。",
                    error_code="PACKAGE_OFFLINE",
                )
                return None
            try:
                manifest = verify_manifest(
                    raw_manifest, self.trust
                )
            except PromptPackageError as exc:
                result = self._result_for_error(exc)
                self._record(
                    result,
                    f"提示词清单未通过校验：{exc.message}；"
                    "继续使用已验证版本或内置文字。",
                    error_code=exc.code,
                )
                return None
            try:
                raw = self._channel_package_fetcher(self.trust, manifest)
            except PromptPackageNetworkError as exc:
                self._record(
                    "offline",
                    f"{exc.message}；继续使用已验证版本或内置文字。",
                    error_code=exc.code,
                )
                return None
            except Exception as exc:  # noqa: BLE001
                self._record(
                    "offline",
                    f"检查提示词更新失败：{exc}；继续使用已验证版本或内置文字。",
                    error_code="PACKAGE_OFFLINE",
                )
                return None
            try:
                package = verify_package_for_manifest(
                    raw,
                    manifest,
                    self.trust,
                    client_version=self.trust.client_version,
                )
            except PromptPackageError as exc:
                result = self._result_for_error(exc)
                self._record(
                    result,
                    f"提示词包未通过校验：{exc.message}；"
                    "继续使用已验证版本或内置文字。",
                    error_code=exc.code,
                )
                return None
            return raw, package, raw_manifest
        try:
            raw = self._fetcher(self.trust)
        except PromptPackageNetworkError as exc:
            self._record(
                "offline",
                f"{exc.message}；继续使用已验证版本或内置文字。",
                error_code=exc.code,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - network never blocks manual work
            self._record(
                "offline",
                f"检查提示词更新失败：{exc}；继续使用已验证版本或内置文字。",
                error_code="PACKAGE_OFFLINE",
            )
            return None
        try:
            package = verify_package(
                raw, self.trust, client_version=self.trust.client_version
            )
        except PromptPackageError as exc:
            result = self._result_for_error(exc)
            self._record(
                result,
                f"提示词包未通过校验：{exc.message}；"
                "继续使用已验证版本或内置文字。",
                error_code=exc.code,
            )
            return None
        return raw, package, None

    def _check_locked(self) -> None:
        candidate = self._candidate_package()
        if candidate is None:
            return
        raw, package, manifest_raw = candidate
        state = self.store.read_state()
        accepted_result = self._check_accepted(package, state)
        if accepted_result in (
            "rollback_rejected",
            "sequence_conflict",
            "identity_conflict",
        ):
            return
        if accepted_result == "same":
            cached, _cache_error = self._active_cache(state.get("active"))
            if (
                cached is not None
                and cached.content_sha256 == package.content_sha256
                and self._activated_content_sha256 == package.content_sha256
            ):
                self._record(
                    "no_update",
                    f"已是最新提示词功能包 r{package.release_sequence}。",
                    package=package,
                )
                return
        self.store.stage_pending(raw, package, manifest_raw=manifest_raw)
        try:
            self._apply(package)
        except (
            PromptPackageError,
            LocalPromptBundleConflict,
            LocalPromptContractRegression,
            LocalValidationError,
        ) as exc:
            self.store.clear_pending()
            self._record(
                "rejected",
                f"提示词包未能启用：{getattr(exc, 'message', exc)}；"
                "继续使用已验证版本或内置文字。",
                package=package,
                error_code=getattr(exc, "code", "PACKAGE_REJECTED"),
            )
            return
        except Exception as exc:  # noqa: BLE001 - keep pending for a later retry
            code = getattr(exc, "code", "PACKAGE_ENABLE_FAILED")
            self._record(
                "failed",
                f"提示词包启用失败：{getattr(exc, 'message', exc)}；"
                "继续使用已验证版本或内置文字。",
                package=package,
                error_code=str(code),
            )
            return
        self.store.activate(raw, package, manifest_raw=manifest_raw)
        self._activated_content_sha256 = package.content_sha256
        self.runtime.prompt_package_builtin_only = False
        self._record(
            "updated" if accepted_result is None else "no_update",
            (
                f"已启用提示词功能包 r{package.release_sequence}。"
                if accepted_result is None
                else f"已用同一受信包修复本地缓存 r{package.release_sequence}。"
            ),
            package=package,
        )

    # ------------------------------------------------------------------
    # Startup / background
    # ------------------------------------------------------------------
    def startup(self) -> None:
        """Verify and re-apply the cached package after restore/restart.

        A bad pending package must not prevent reuse of a still-valid active
        package.  A transient pending apply failure keeps pending for a later
        retry while the active package is still restored.
        """
        state = self.store.read_state()
        pending_raw = self.store.load_pending_raw() if state.get("pending") else None
        active_raw = self.store.load_active_raw() if state.get("active") else None
        preserve_pending = False
        if pending_raw is not None:
            if self._startup_apply(pending_raw, state, pending=True):
                return
            preserve_pending = self.store.read_state().get("pending") is not None
        if active_raw is not None:
            self._startup_apply(
                active_raw,
                self.store.read_state(),
                pending=False,
                clear_pending_on_activate=not preserve_pending,
            )
        self._fallback_if_no_valid_cache("startup_no_valid_cache")

    def _startup_apply(
        self,
        raw: bytes,
        state: dict[str, Any],
        *,
        pending: bool,
        clear_pending_on_activate: bool = True,
    ) -> bool:
        if not self.trust.configured:
            self._record(
                "unconfigured",
                "提示词包来源未配置；已忽略本地缓存，当前使用程序内置文字。",
                error_code="PACKAGE_SOURCE_UNCONFIGURED",
            )
            return False
        try:
            package = verify_package(
                raw, self.trust, client_version=self.trust.client_version
            )
        except PromptPackageError as exc:
            self._record(
                "cache_invalid",
                f"本地提示词包缓存校验失败：{exc.message}；"
                "当前使用程序已登记文字或内置文字。",
                error_code=exc.code,
            )
            if pending:
                self.store.clear_pending()
            return False
        metadata = state.get("pending") if pending else state.get("active")
        manifest_raw = None
        if self.trust.channel is not None:
            manifest_raw = (
                self.store.load_pending_manifest()
                if pending
                else self.store.load_active_manifest()
            )
        _manifest, proof_error = self._verify_cached_manifest(
            raw, package, manifest_raw, metadata
        )
        if proof_error is not None:
            self._record(
                "cache_invalid",
                f"本地提示词包缺少或无法验证签名清单（{proof_error}）；"
                "已忽略，可在线检查修复。",
                error_code=proof_error,
            )
            if pending:
                self.store.clear_pending()
            return False
        accepted = state.get("accepted") or {}
        if isinstance(accepted, dict):
            accepted_sequence = accepted.get("release_sequence")
            accepted_hash = accepted.get("content_sha256")
            if (
                isinstance(accepted_sequence, int)
                and package.release_sequence < accepted_sequence
            ):
                self._record(
                    "cache_stale",
                    "本地提示词包缓存低于已接受发布序号，已忽略。",
                    package=package,
                    error_code="PACKAGE_SEQUENCE_ROLLBACK",
                )
                if pending:
                    self.store.clear_pending()
                return False
            if (
                isinstance(accepted_sequence, int)
                and package.release_sequence == accepted_sequence
                and isinstance(accepted_hash, str)
                and accepted_hash != package.content_sha256
            ):
                self._record(
                    "sequence_conflict",
                    "已接受发布序号相同但内容摘要不同，已拒绝覆盖账本。",
                    package=package,
                    error_code="PACKAGE_SEQUENCE_CONFLICT",
                )
                if pending:
                    self.store.clear_pending()
                return False
        try:
            self._apply(package)
        except (
            PromptPackageError,
            LocalPromptBundleConflict,
            LocalPromptContractRegression,
            LocalValidationError,
        ) as exc:
            code = getattr(exc, "code", "PACKAGE_REJECTED")
            result = (
                "cache_stale"
                if isinstance(exc, LocalPromptContractRegression)
                or code
                in (
                    "PACKAGE_DEFAULT_ROLLBACK",
                    "PACKAGE_IDENTITY_CONFLICT",
                )
                else "cache_invalid"
            )
            self._record(
                result,
                f"本地提示词包未能重新启用：{getattr(exc, 'message', exc)}；"
                "当前使用内置或已登记文字。",
                package=package,
                error_code=str(code),
            )
            if pending:
                self.store.clear_pending()
            return False
        except Exception as exc:  # noqa: BLE001 - never block startup
            code = getattr(exc, "code", "PACKAGE_ENABLE_FAILED")
            self._record(
                "failed",
                f"本地提示词包未能重新启用：{getattr(exc, 'message', exc)}；"
                "当前使用内置或已登记文字。",
                package=package,
                error_code=str(code),
            )
            return False
        self.store.activate(
            raw,
            package,
            manifest_raw=manifest_raw,
            clear_pending=clear_pending_on_activate,
        )
        self._activated_content_sha256 = package.content_sha256
        self.runtime.prompt_package_builtin_only = False
        return True

    def start_background_check(self) -> None:
        """One rate-limited background check per launch, never when unset."""
        if not self.trust.configured or self._background_started:
            return
        self._background_started = True

        def run() -> None:
            try:
                self.check(manual=False)
            except Exception:  # noqa: BLE001 - background must stay silent
                pass

        thread = threading.Thread(
            target=run,
            name="prompt-package-check",
            daemon=True,
        )
        thread.start()
