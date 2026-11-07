"""Synthetic listening fixtures and a real cold-open helper.

The fixture never reads the teacher's real photos or database.  It creates
small synthetic JPEG/PNG images, posts multipart requests through the real
loopback test server, and provides a subprocess entry point that opens a
restored database with the current source code for the cold-open comparison.
"""

from __future__ import annotations

import hashlib
import io
import json
import secrets
import sys
import uuid
from datetime import date, datetime, timezone
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select, text

from app.local import listening_assets, listening_service, profile_service
from app.local.models import LocalListeningAsset, LocalListeningRecord
from app.local.runtime import LocalRuntime


def jpeg_bytes(color: tuple[int, int, int] = (200, 30, 30), size=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def png_bytes(color: tuple[int, int, int] = (20, 120, 200), size=(48, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def request_id() -> str:
    return str(uuid.uuid4())


def post_multipart(
    client,
    path: str,
    fields: dict[str, str],
    *,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[int, Any]:
    """Post one bounded multipart file through the real loopback server."""
    boundary = "----kgm-listening-" + secrets.token_hex(12)
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    connection = HTTPConnection(client.host, client.port, timeout=60.0)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-App-Session": client.token,
                "Origin": client.origin,
                "Host": f"{client.host}:{client.port}",
            },
        )
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        status = response.status
    finally:
        connection.close()
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def get_bytes(client, path: str) -> tuple[int, bytes, dict[str, str]]:
    """Read one binary response through the real loopback server."""
    connection = HTTPConnection(client.host, client.port, timeout=60.0)
    try:
        connection.request(
            "GET",
            path,
            headers={
                "X-App-Session": client.token,
                "Origin": client.origin,
                "Host": f"{client.host}:{client.port}",
            },
        )
        response = connection.getresponse()
        payload = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, payload, headers
    finally:
        connection.close()


def listening_snapshot(
    runtime: LocalRuntime, *, profile_id: str, record_id: str
) -> dict[str, Any]:
    """Read one record plus every managed asset hash through the service."""
    session = runtime.session()
    try:
        record = listening_service.read_record(
            session, profile_id=profile_id, record_id=record_id
        )
        asset_rows = session.execute(
            select(LocalListeningAsset)
            .where(LocalListeningAsset.record_id == record_id)
            .order_by(LocalListeningAsset.id)
        ).scalars().all()
        assets = []
        for asset in asset_rows:
            payload, metadata = listening_assets.read_asset(
                session,
                runtime,
                profile_id=profile_id,
                record_id=record_id,
                asset_id=asset.id,
            )
            assets.append(
                {
                    "asset_id": asset.id,
                    "content_hash": metadata["content_hash"],
                    "byte_size": metadata["byte_size"],
                    "width": metadata["width"],
                    "height": metadata["height"],
                    "orientation": metadata["orientation"],
                    "mime_type": metadata["mime_type"],
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "payload_bytes": len(payload),
                }
            )
        return {"record": record, "assets": assets}
    finally:
        session.close()


def cold_open(data_dir: str, credential_root: str) -> dict[str, Any]:
    """Open a restored database with a fresh runtime and read listening data."""
    runtime = LocalRuntime(
        Path(data_dir), credential_root=Path(credential_root)
    )
    try:
        runtime.prepare()
        session = runtime.session()
        try:
            context = profile_service.require_context(session, date.today())
            profile_id = context.profile.id
            records = session.execute(
                select(LocalListeningRecord).order_by(LocalListeningRecord.id)
            ).scalars().all()
            result = {
                "revision": runtime.current_revision,
                "profile_id": profile_id,
                "records": [],
                "assets": [],
            }
            for record in records:
                dto = listening_service.read_record(
                    session, profile_id=profile_id, record_id=record.id
                )
                result["records"].append(dto)
                asset_rows = session.execute(
                    select(LocalListeningAsset)
                    .where(LocalListeningAsset.record_id == record.id)
                    .order_by(LocalListeningAsset.id)
                ).scalars().all()
                for asset in asset_rows:
                    payload, metadata = listening_assets.read_asset(
                        session,
                        runtime,
                        profile_id=profile_id,
                        record_id=record.id,
                        asset_id=asset.id,
                    )
                    result["assets"].append(
                        {
                            "record_id": record.id,
                            "asset_id": asset.id,
                            "content_hash": metadata["content_hash"],
                            "byte_size": metadata["byte_size"],
                            "payload_sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    )
            counts = {}
            for table in (
                "local_listening_records",
                "local_listening_domains",
                "local_listening_evaluation_choices",
                "local_listening_photo_groups",
                "local_listening_assets",
                "local_listening_operations",
            ):
                counts[table] = int(
                    session.execute(
                        text(f'SELECT COUNT(*) FROM "{table}"')
                    ).scalar_one()
                )
            result["counts"] = counts
            return result
        finally:
            session.close()
    finally:
        runtime.dispose()


def _write_old_package(
    db_path: Path,
    data_dir: Path,
    output: Path,
    *,
    password: str | None,
    app_version: str,
) -> None:
    """Build a Format 1 package whose manifest has only old observation entries."""
    import zipfile

    from app.local import backup_format, backup_validate

    scratch = output.parent / "old-package-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    facts = backup_validate.inspect_source_database(db_path, scratch_dir=scratch)
    resources: dict[str, bytes] = {}
    entries = []
    for entry in backup_validate.iter_registered_resources(db_path):
        payload = data_dir.joinpath(*entry["path"].split("/")).read_bytes()
        resources[entry["path"]] = payload
        entries.append(
            {
                "asset_id": entry["asset_id"],
                "bytes": len(payload),
                "derivative_id": entry["derivative_id"],
                "kind": entry["kind"],
                "observation_id": entry["observation_id"],
                "path": entry["path"],
                "sha256": entry["sha256"],
            }
        )
    db_bytes = db_path.read_bytes()
    manifest = {
        "format_version": 1,
        "snapshot_id": "b" * 32,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": app_version,
        "database_revision": facts["source_revision"],
        "ai_contracts": facts["source_ai_contracts"],
        "database": {
            "path": "db/kindergarten.db",
            "bytes": len(db_bytes),
            "sha256": facts["source_sha256"],
        },
        "resources": entries,
        "counts": {
            "database_bytes": len(db_bytes),
            "resources": len(entries),
            "resources_bytes": sum(len(value) for value in resources.values()),
        },
        "source_identity": {"fixture": "old-listening-compat"},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        )
        archive.writestr("db/kindergarten.db", db_bytes)
        for name in sorted(resources):
            archive.writestr(name, resources[name])
    payload = buffer.getvalue()
    if password is None:
        header = backup_format.encode_header(mode=1, payload_len=len(payload))
        output.write_bytes(header + payload)
        return
    import os

    salt = os.urandom(backup_format.SALT_LEN)
    nonce = os.urandom(backup_format.NONCE_LEN)
    key = backup_format.derive_key(password, salt)
    header = backup_format.encode_header(
        mode=2, payload_len=len(payload), salt=salt, nonce=nonce
    )
    cipher = io.BytesIO()
    tag = backup_format.encrypt_payload(
        io.BytesIO(payload),
        cipher,
        key=key,
        nonce=nonce,
        aad=header,
        length=len(payload),
    )
    output.write_bytes(header + cipher.getvalue() + tag)


def build_old_0008_database(root: Path) -> tuple[Path, Path]:
    """Create the frozen 0007 fixture, then upgrade it to the 0008 head."""
    from alembic import command

    from app.local.migrate import alembic_config
    from tests.local.backup_fixture_support import create_old_0007_fixture

    root = Path(root)
    db = root / "kindergarten.db"
    data = root / "data"
    create_old_0007_fixture(db, data)
    command.upgrade(alembic_config(db), "20261102_0008_local_weekly_ai")
    return db, data


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4 or args[0] != "cold_open":
        raise SystemExit(
            "usage: listening_fixture_support cold_open <data_dir> "
            "<credential_root> <output_json>"
        )
    result = cold_open(args[1], args[2])
    Path(args[3]).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
