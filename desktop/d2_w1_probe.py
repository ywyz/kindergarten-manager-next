"""D2 W1 frozen console probe: real local runtime + DPAPI/AES credential save.

This module is the *child* entry point of the W1 frozen verification. It runs
inside the PyInstaller **onedir** bundle with no development ``PYTHONPATH`` and
uses only the resources bundled with the executable (the local Alembic INI and
``migrations_local`` tree are added inside the package).

Two modes share one database file and one credential root:

- ``init``: prepare the frozen runtime, initialize one local profile, save an
  AI configuration whose secret arrives **only through stdin**, then read the
  redacted configuration back.
- ``verify``: restart against the same database and credential root, read the
  configuration, load the DPAPI-protected master key, AES-GCM-decrypt the
  stored secret and compare it to the secret supplied again through stdin.

The secret is never written to argv, the environment, a temporary file or the
result JSON; only booleans, versions and redacted error codes are emitted. This
is a no-UI verification probe: it starts no executor, no network call and no
W2-W6 work.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

BASE_URL = "https://api.example.com/v1"
MODEL = "probe-model"


def _read_secret() -> str:
    """Read the whole stdin as the secret (no echo, no argv/env)."""
    data = sys.stdin.buffer.read()
    return data.decode("utf-8").rstrip("\r\n")


def _bundle_facts() -> dict:
    from app.local import migrate

    meipass = Path(getattr(sys, "_MEIPASS", ""))
    migrations = Path(migrate.MIGRATIONS_DIR)
    ini = Path(migrate.ALEMBIC_INI_PATH)
    try:
        resolved = migrations.resolve()
        inside = meipass != Path("") and (
            resolved == meipass or meipass in resolved.parents
        )
    except OSError:
        inside = False
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "migrations_inside_bundle": bool(inside),
        "versions_present": (migrations / "versions").is_dir(),
        "ini_present": ini.is_file(),
    }


def _bundle_hashes(session) -> dict:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT task_type, bundle_hash FROM local_prompt_bundles "
            "ORDER BY task_type"
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def _credential_facts(session) -> dict:
    from sqlalchemy import select

    from app.local.models import (
        LocalAIConfigVersion,
        LocalAICredential,
        LocalAIState,
    )

    state = session.scalars(select(LocalAIState)).first()
    if state is None:
        raise RuntimeError("no local_ai_state row")
    facts = {
        "profile_id": state.profile_id,
        "database_uuid": state.database_uuid,
        "key_id": None,
        "credential_id": None,
        "nonce": None,
        "ciphertext": None,
    }
    if state.current_config_version is None:
        return facts
    config = session.get(
        LocalAIConfigVersion, (state.profile_id, state.current_config_version)
    )
    if config is None or config.credential_id is None:
        return facts
    credential = session.scalars(
        select(LocalAICredential).where(
            LocalAICredential.profile_id == state.profile_id,
            LocalAICredential.id == config.credential_id,
        )
    ).first()
    if credential is None:
        return facts
    facts.update(
        {
            "key_id": credential.key_id,
            "credential_id": credential.id,
            "nonce": credential.nonce,
            "ciphertext": credential.ciphertext,
        }
    )
    return facts


def _run_init(args, secret: str) -> dict:
    from app.local import ai_config_service, profile_service
    from app.local.normalize import normalize_initialization
    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(args.data_dir, credential_root=args.credential_root)
    inspection = runtime.prepare()
    try:
        session = runtime.session()
        try:
            normalized = normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="冻结探针教师",
                class_name="中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-09-30",
                school_name="冻结探针园",
            )
            payload, created = profile_service.initialize(session, normalized)
        finally:
            session.close()

        session = runtime.session()
        try:
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=0,
                base_url=BASE_URL,
                model=MODEL,
                secret=secret,
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
        finally:
            session.close()

        session = runtime.session()
        try:
            config = ai_config_service.get_config(
                session, credential_root=runtime.credential_root
            )
            facts = _credential_facts(session)
            bundles = _bundle_hashes(session)
        finally:
            session.close()

        return {
            "ok": True,
            "mode": "init",
            "created": created,
            "head": inspection.current_revision,
            "profile_id": payload["profile"]["id"],
            "ai_config_version": config.ai_config_version,
            "configured": config.configured,
            "has_secret": config.has_secret,
            "ready": config.ready,
            "database_uuid": facts["database_uuid"],
            "key_id": facts["key_id"],
            "bundle_hashes": bundles,
            **_bundle_facts(),
        }
    finally:
        runtime.dispose()


def _run_verify(args, secret: str) -> dict:
    from app.local import ai_config_service
    from app.local.credentials import CredentialStore, SavedSecret
    from app.local.runtime import LocalRuntime

    runtime = LocalRuntime(args.data_dir, credential_root=args.credential_root)
    inspection = runtime.prepare()
    try:
        session = runtime.session()
        try:
            config = ai_config_service.get_config(
                session, credential_root=runtime.credential_root
            )
            facts = _credential_facts(session)
        finally:
            session.close()

        key_id = facts["key_id"]
        database_uuid = facts["database_uuid"]
        if not key_id or facts["nonce"] is None or facts["ciphertext"] is None:
            raise RuntimeError("no stored credential material to decrypt")
        store = CredentialStore(runtime.credential_root, database_uuid)
        master_key = store.load_master_key(key_id)
        saved = SavedSecret(
            key_id=key_id,
            nonce=facts["nonce"],
            ciphertext=facts["ciphertext"],
        )
        decrypted = store.decrypt_secret(
            master_key, saved, facts["profile_id"], facts["credential_id"]
        )
        matches = decrypted == secret
        return {
            "ok": True,
            "mode": "verify",
            "head": inspection.current_revision,
            "ai_config_version": config.ai_config_version,
            "configured": config.configured,
            "has_secret": config.has_secret,
            "ready": config.ready,
            "decrypted_matches": matches,
            "database_uuid": database_uuid,
            "key_id": key_id,
            **_bundle_facts(),
        }
    finally:
        runtime.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="D2 W1 frozen credential probe")
    parser.add_argument("--mode", choices=("init", "verify"), required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--credential-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    secret = _read_secret()
    try:
        payload = (
            _run_init(args, secret)
            if args.mode == "init"
            else _run_verify(args, secret)
        )
    except BaseException as exc:  # noqa: BLE001 - redacted failure evidence
        code = getattr(exc, "code", None)
        payload = {
            "ok": False,
            "mode": args.mode,
            "error": type(exc).__name__,
            "code": code,
        }
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        print(f"probe {args.mode} failed: {type(exc).__name__} {code}")
        return 1

    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    print(f"probe {args.mode} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
