import argparse
import getpass
import sys
import warnings

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import security
from app.config import settings
from app.models import Account
from app.services import auth_service


def _require_mysql_pymysql_url(raw_url: str) -> None:
    """Reject non-pymysql URLs without a database name before any connection is opened."""
    if not raw_url:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        sys.exit(1)
    try:
        url = make_url(raw_url)
    except Exception:
        print("DATABASE_URL 格式无效。", file=sys.stderr)
        sys.exit(1)
    if url.drivername != "mysql+pymysql":
        print("DATABASE_URL 必须使用 mysql+pymysql 驱动。", file=sys.stderr)
        sys.exit(1)
    if not url.database:
        print("DATABASE_URL 未指定数据库名。", file=sys.stderr)
        sys.exit(1)


def _reset_admin_password(username: str) -> None:
    raw_url = settings.database_url.get_secret_value()
    _require_mysql_pymysql_url(raw_url)

    try:
        normalized = security.normalize_username(username)
    except ValueError as e:
        print(f"用户名不符合规范: {e}", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(raw_url, poolclass=NullPool)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    # Read phase: locate the target in a short read-only transaction.
    try:
        with Session() as db:
            account = db.scalar(
                select(Account).where(Account.username == normalized)
            )
            if account is None or account.role != "admin":
                print("目标账号不存在或不是管理员。", file=sys.stderr)
                sys.exit(1)
            target_id = account.id
            target_version = account.version
    except SQLAlchemyError:
        print("数据库读取失败，未执行任何更改。", file=sys.stderr)
        sys.exit(1)

    print(f"目标账号: {normalized}")

    if not sys.stdin.isatty():
        print("必须在交互式终端中执行密码重置。", file=sys.stderr)
        sys.exit(1)

    # Prevent getpass from falling back to stdout echo on unsupported terminals.
    warnings.simplefilter("error", getpass.GetPassWarning)

    try:
        new_password = getpass.getpass("请输入新密码: ")
        confirm = getpass.getpass("请再次输入新密码: ")
    except EOFError:
        print("无法读取密码输入。", file=sys.stderr)
        sys.exit(1)
    except getpass.GetPassWarning:
        print("密码输入回显被阻止，请在支持安全输入的终端执行。", file=sys.stderr)
        sys.exit(1)

    if new_password != confirm:
        print("两次输入不一致，未执行任何更改。", file=sys.stderr)
        sys.exit(1)
    try:
        security.validate_password(new_password)
    except ValueError as e:
        print(f"密码不符合要求: {e}", file=sys.stderr)
        sys.exit(1)

    ok = input("确认重置并撤销该账号全部会话？(y/N): ")
    if ok.strip().lower() != "y":
        print("已取消。")
        sys.exit(0)

    # Hash outside the write transaction.
    new_password_hash = security.hash_password(new_password)

    # Write phase: lock, verify version, apply the shared atomic update rule.
    try:
        with Session() as db:
            with db.begin():
                locked = auth_service._lock_account(db, target_id)
                if locked is None or locked.role != "admin":
                    print("目标账号不存在或不是管理员。", file=sys.stderr)
                    sys.exit(1)
                if locked.version != target_version:
                    print("目标账号在确认后已被修改，未执行任何更改。", file=sys.stderr)
                    sys.exit(1)
                auth_service._apply_password_reset(
                    db,
                    locked,
                    new_password_hash,
                    operator_id=None,
                    operator_type="server_operator",
                    action="cli_reset_admin_password",
                )
    except SystemExit:
        raise
    except SQLAlchemyError:
        print("数据库操作失败，未执行任何更改。", file=sys.stderr)
        sys.exit(1)

    print(f"管理员 {normalized} 密码已重置，全部会话已撤销。")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Kindergarten Manager server-side maintenance commands.",
    )
    subparsers = parser.add_subparsers(dest="command")
    reset = subparsers.add_parser(
        "reset-admin-password",
        help="Reset an existing admin password from the server console.",
    )
    reset.add_argument("--username", required=True, help="Admin username to reset")

    args = parser.parse_args()
    if args.command != "reset-admin-password":
        parser.print_help()
        sys.exit(1)

    _reset_admin_password(args.username.strip().lower())


if __name__ == "__main__":
    main()
