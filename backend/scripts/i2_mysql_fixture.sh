#!/usr/bin/env bash
#
# I2 MySQL fixture: refresh an isolated I2 test database and run migrations.
# This script is NEVER run automatically by the test suite. Run it manually
# only after explicit resource authorization.
#
# Usage:
#   export KG_TEST_DATABASE_URL='mysql+pymysql://kg_test_i2:pass@127.0.0.1:3306/kindergarten_test_i2'
#   scripts/i2_mysql_fixture.sh i2        # migrate from I1 with fixture preservation check
#   scripts/i2_mysql_fixture.sh fresh     # clean-chain migration from scratch
#
# Required env:
#   KG_TEST_DATABASE_URL  application DSN including the target database name.
#                         The account must have DDL/DML rights on the two
#                         whitelisted I2 databases (created by main beforehand).
#
# No credentials are printed. Errors only mention the variable name or a
# redacted host/driver.
set -euo pipefail

MODE="${1:-}"
I2_DB="kindergarten_test_i2"
FRESH_DB="kindergarten_test_i2_fresh"
I1_HEAD="20260921_i1_identity_reg"
EXPECTED_HEAD="20260922_i2_terms_calendar"

if [[ "$MODE" != "i2" && "$MODE" != "fresh" ]]; then
    echo "Usage: $0 {i2|fresh}" >&2
    echo "Set KG_TEST_DATABASE_URL to a whitelisted I2 database on port 13384." >&2
    exit 1
fi

: "${KG_TEST_DATABASE_URL:?set KG_TEST_DATABASE_URL}"

cd "$(dirname "$0")/.."

export APP_DISABLE_DOTENV=1
# Make the application see exactly the target DSN; no other .env may redirect it.
export DATABASE_URL="$KG_TEST_DATABASE_URL"

# ---------------------------------------------------------------------------
# Validate DSN without printing credentials.
# ---------------------------------------------------------------------------
if ! .venv/bin/python - "$MODE" "$KG_TEST_DATABASE_URL" <<'PY'; then
import sys
from urllib.parse import urlsplit

mode = sys.argv[1]
url = sys.argv[2]
u = urlsplit(url)
errors = []
if u.scheme != "mysql+pymysql":
    errors.append(f"KG_TEST_DATABASE_URL driver must be mysql+pymysql (got {u.scheme})")
if u.hostname not in ("127.0.0.1", "localhost"):
    errors.append(f"KG_TEST_DATABASE_URL host must be 127.0.0.1 or localhost (got {u.hostname})")
if u.port != 13384:
    errors.append(f"KG_TEST_DATABASE_URL port must be 13384 (got {u.port})")
allowed = {"kindergarten_test_i2", "kindergarten_test_i2_fresh"}
db = (u.path or "").lstrip("/")
if db not in allowed:
    errors.append(f"KG_TEST_DATABASE_URL database must be one of {allowed} (got {db})")
if mode == "fresh" and db != "kindergarten_test_i2_fresh":
    errors.append("fresh mode requires database kindergarten_test_i2_fresh")
if mode == "i2" and db != "kindergarten_test_i2":
    errors.append("i2 mode requires database kindergarten_test_i2")
if errors:
    for e in errors:
        print(e, file=sys.stderr)
    sys.exit(1)
PY
    echo "KG_TEST_DATABASE_URL validation failed" >&2
    exit 1
fi

echo "[1/4] Checking MySQL 8.4 / InnoDB for target database (redacted)"
.venv/bin/python - <<'PY'
import os
from sqlalchemy import create_engine, text
from app.config import settings

url = settings.database_url.get_secret_value()
eng = create_engine(url)
with eng.connect() as c:
    version = c.execute(text("SELECT VERSION()")).scalar()
    engine_var = c.execute(text("SHOW VARIABLES LIKE 'default_storage_engine'")).fetchone()
if not version or not version.startswith("8.4"):
    raise AssertionError(f"MySQL 8.4 required, found {version}")
if not engine_var or engine_var[1].lower() != "innodb":
    raise AssertionError("MySQL default storage engine must be InnoDB")
print("MySQL", version.split("-")[0], "InnoDB OK")
PY

echo "[2/4] Cleaning target database and migrating to I1 head (when needed)"
if [ "$MODE" = "i2" ]; then
    echo "[2a/4] Dropping existing tables for a clean I1 baseline"
    .venv/bin/python - <<'PY'
from sqlalchemy import create_engine, text
from app.config import settings

url = settings.database_url.get_secret_value()
eng = create_engine(url)
with eng.begin() as c:
    c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    rows = c.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE()"
    )).fetchall()
    for (table_name,) in rows:
        c.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
    c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
PY

    DATABASE_URL="$KG_TEST_DATABASE_URL" .venv/bin/alembic upgrade "$I1_HEAD"

    echo "[2b/4] Seeding realistic I1-format fixtures"
    .venv/bin/python - <<'PY'
import json
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text
from app import security
from app.config import settings

url = settings.database_url.get_secret_value()
eng = create_engine(url)

now = datetime.now(timezone.utc).replace(tzinfo=None)
expires = now + timedelta(hours=12)
admin_id = security.generate_id()
teacher_id = security.generate_id()
session_id = security.generate_id()
record_id = security.generate_id()
admin_hash = security.hash_password("Adminpass123")
teacher_hash = security.hash_password("Teacherpass123")
admin_token, admin_token_hash = security.create_session()

with eng.begin() as c:
    c.execute(text("DELETE FROM operation_records"))
    c.execute(text("DELETE FROM sessions"))
    c.execute(text("DELETE FROM first_admin_control"))
    c.execute(text("DELETE FROM accounts"))
    c.execute(text(
        "INSERT INTO first_admin_control (id, claimed, first_admin_id) "
        "VALUES ('singleton', 0, NULL)"
    ))
    c.execute(text(
        "INSERT INTO accounts (id, username, password_hash, display_name, "
        "role, is_active, version, auth_version, created_at, updated_at) "
        "VALUES (:id, :username, :hash, NULL, 'admin', 1, 1, 1, :now, :now)"
    ), {"id": admin_id, "username": "legacyadmin", "hash": admin_hash, "now": now})
    c.execute(text(
        "INSERT INTO accounts (id, username, password_hash, display_name, "
        "role, is_active, version, auth_version, created_at, updated_at) "
        "VALUES (:id, :username, :hash, NULL, 'teacher', 1, 1, 1, :now, :now)"
    ), {"id": teacher_id, "username": "legacyteacher", "hash": teacher_hash, "now": now})
    c.execute(text(
        "UPDATE first_admin_control SET claimed = 1, first_admin_id = :aid "
        "WHERE id = 'singleton'"
    ), {"aid": admin_id})
    c.execute(text(
        "INSERT INTO sessions (id, token_hash, account_id, auth_version, "
        "created_at, expires_at, revoked_at) "
        "VALUES (:id, :hash, :aid, 1, :now, :expires, NULL)"
    ), {"id": session_id, "hash": admin_token_hash, "aid": admin_id, "now": now, "expires": expires})
    c.execute(text(
        "INSERT INTO operation_records (id, created_at, operator_id, "
        "operator_type, action, target_account_id, account_version_after) "
        "VALUES (:id, :now, :aid, 'account', 'register', :aid, 1)"
    ), {"id": record_id, "now": now, "aid": admin_id})

# Snapshot the actual persisted rows (MySQL DATETIME truncates microseconds,
# so we compare what the database actually stored, not the pre-insert values).
with eng.begin() as c:
    admin_row = c.execute(text(
        "SELECT id, username, password_hash, display_name, role, is_active, "
        "version, auth_version, created_at, updated_at FROM accounts WHERE id = :id"
    ), {"id": admin_id}).fetchone()
    teacher_row = c.execute(text(
        "SELECT id, username, password_hash, display_name, role, is_active, "
        "version, auth_version, created_at, updated_at FROM accounts WHERE id = :id"
    ), {"id": teacher_id}).fetchone()
    sess_row = c.execute(text(
        "SELECT id, token_hash, account_id, auth_version, created_at, expires_at, "
        "revoked_at FROM sessions WHERE id = :id"
    ), {"id": session_id}).fetchone()
    # At I1 head the record has no generic target columns yet.
    rec_row = c.execute(text(
        "SELECT id, created_at, operator_id, operator_type, action, "
        "target_account_id, account_version_after FROM operation_records WHERE id = :id"
    ), {"id": record_id}).fetchone()


def _row_dict(row):
    return {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in row._mapping.items()
    }


# Snapshot kept in a private temp file (mode 600); never echoed.
snapshot = {
    "admin": _row_dict(admin_row),
    "teacher": _row_dict(teacher_row),
    "session": _row_dict(sess_row),
    "record": _row_dict(rec_row),
}
snapshot_path = "/tmp/kg-next-i2-fixture-snapshot.json"
with open(snapshot_path, "w") as f:
    json.dump(snapshot, f)
os.chmod(snapshot_path, 0o600)
print("seeded I1 fixtures; snapshot kept at", snapshot_path)
PY

    echo "[3/4] Upgrading from I1 to I2 head"
    DATABASE_URL="$KG_TEST_DATABASE_URL" .venv/bin/alembic upgrade head

    echo "[4/4] Verifying I1 fixture preservation after I2 migration"
    .venv/bin/python - <<'PY'
import json
from datetime import datetime
from sqlalchemy import create_engine, text
from app.config import settings

with open("/tmp/kg-next-i2-fixture-snapshot.json") as f:
    snap = json.load(f)


def _row_dict(row):
    return {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in row._mapping.items()
    }


url = settings.database_url.get_secret_value()
eng = create_engine(url)
with eng.begin() as c:
    admin = c.execute(text(
        "SELECT id, username, password_hash, display_name, role, is_active, "
        "version, auth_version, created_at, updated_at FROM accounts WHERE id = :id"
    ), {"id": snap["admin"]["id"]}).fetchone()
    assert admin is not None, "admin account missing"
    assert _row_dict(admin) == snap["admin"], "admin row changed"

    teacher = c.execute(text(
        "SELECT id, username, password_hash, display_name, role, is_active, "
        "version, auth_version, created_at, updated_at FROM accounts WHERE id = :id"
    ), {"id": snap["teacher"]["id"]}).fetchone()
    assert teacher is not None, "teacher account missing"
    assert _row_dict(teacher) == snap["teacher"], "teacher row changed"

    sess = c.execute(text(
        "SELECT id, token_hash, account_id, auth_version, created_at, expires_at, "
        "revoked_at FROM sessions WHERE id = :id"
    ), {"id": snap["session"]["id"]}).fetchone()
    assert sess is not None, "session missing"
    assert _row_dict(sess) == snap["session"], "session row changed"

    rec = c.execute(text(
        "SELECT id, created_at, operator_id, operator_type, action, "
        "target_account_id, account_version_after FROM operation_records WHERE id = :id"
    ), {"id": snap["record"]["id"]}).fetchone()
    assert rec is not None, "operation record missing"
    assert _row_dict(rec) == snap["record"], "operation record changed"

    # Generic target columns must have been back-filled by the migration.
    generic = c.execute(text(
        "SELECT target_type, target_id, target_version_after FROM operation_records WHERE id = :id"
    ), {"id": snap["record"]["id"]}).fetchone()
    assert generic.target_type == "account"
    assert generic.target_id == snap["record"]["operator_id"]
    assert generic.target_version_after == snap["record"]["account_version_after"]

    control = c.execute(text(
        "SELECT id, claimed, first_admin_id FROM first_admin_control WHERE id = 'singleton'"
    )).fetchone()
    assert control.claimed
    assert control.first_admin_id == snap["admin"]["id"]

print("I1 fixtures preserved after I2 migration")
PY
else
    echo "[3/4] Migrating fresh database from scratch"
    DATABASE_URL="$KG_TEST_DATABASE_URL" .venv/bin/alembic upgrade head

    echo "[4/4] Verifying single head"
    ACTUAL="$(DATABASE_URL='$KG_TEST_DATABASE_URL' .venv/bin/alembic heads | awk '{print $1}')"
    if [ "$ACTUAL" != "$EXPECTED_HEAD" ]; then
        echo "Unexpected alembic head: $ACTUAL (want $EXPECTED_HEAD)" >&2
        exit 1
    fi
    echo "Clean-chain migration OK"
fi

echo "I2 fixture ready for database: $MODE"
echo "Run tests with:"
echo "  export APP_DISABLE_DOTENV=1"
echo "  export I2_TEST_ALLOW_DESTRUCTIVE=yes"
echo "  export I2_TEST_DATABASE_URL='\$KG_TEST_DATABASE_URL'"
echo "  .venv/bin/python -m unittest discover -s tests/integration -v"
