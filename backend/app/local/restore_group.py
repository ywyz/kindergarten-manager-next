"""Fixed-component group identity, movement and verification for restore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.local import backup_fs, backup_validate
from app.local.restore_fs import (
    FileIdentity,
    RestorePathSet,
    ensure_private_dir,
    file_identity,
    move_no_replace,
    tree_manifest,
    verify_tree,
)
from app.local.restore_types import RestoreFailure

DB_COMPONENTS = (
    "kindergarten.db",
    "kindergarten.db-wal",
    "kindergarten.db-shm",
    "kindergarten.db-journal",
)
_MAIN_DB = DB_COMPONENTS[0]


def _identity_dict(value: FileIdentity) -> dict[str, Any]:
    return value.as_dict()


def _same_identity(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if bool(actual.get("present")) != bool(expected.get("present")):
        return False
    if not expected.get("present"):
        return True
    return (
        actual.get("volume") == expected.get("volume")
        and actual.get("file_id") == expected.get("file_id")
        and actual.get("size") == expected.get("size")
        and actual.get("sha256") == expected.get("sha256")
    )


def live_db_path(paths: RestorePathSet, name: str) -> Path:
    return paths.data_dir / name


def old_db_path(paths: RestorePathSet, name: str) -> Path:
    return paths.old_dir / "db" / name


def prepared_db_path(paths: RestorePathSet, name: str = _MAIN_DB) -> Path:
    return paths.prepared_dir / "db" / name


def live_assets_path(paths: RestorePathSet) -> Path:
    return paths.data_dir / "observations" / "assets"


def old_assets_path(paths: RestorePathSet) -> Path:
    return paths.old_dir / "assets"


def prepared_assets_path(paths: RestorePathSet) -> Path:
    return paths.prepared_dir / "assets"


def capture_old_group(paths: RestorePathSet) -> dict[str, Any]:
    """Capture the post-close physical old group (never an online package hash)."""
    db: dict[str, Any] = {}
    for name in DB_COMPONENTS:
        db[name] = _identity_dict(file_identity(live_db_path(paths, name)))
    assets = tree_manifest(live_assets_path(paths), strict_regular=False)
    return {"db": db, "assets": assets}


def capture_new_group(paths: RestorePathSet) -> dict[str, Any]:
    db = _identity_dict(file_identity(prepared_db_path(paths)))
    assets = tree_manifest(prepared_assets_path(paths), strict_regular=True)
    return {"db": db, "assets": assets}


def _locate_old_db(
    paths: RestorePathSet, name: str, expected: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    candidates = {
        "live": file_identity(live_db_path(paths, name)).as_dict(),
        "old": file_identity(old_db_path(paths, name)).as_dict(),
    }
    present = [key for key, value in candidates.items() if value["present"]]
    if expected.get("present"):
        matches = [key for key in present if _same_identity(candidates[key], expected)]
        if len(matches) != 1:
            raise RestoreFailure(
                "RESTORE_GROUP_CONFLICT",
                "recovery",
                f"旧数据库组件位置或身份不唯一：{name}",
            )
        return matches[0], candidates[matches[0]]
    if present:
        raise RestoreFailure(
            "RESTORE_GROUP_CONFLICT", "recovery", f"旧数据库组件不应存在：{name}"
        )
    return "absent", candidates["live"]


def _locate_old_assets(
    paths: RestorePathSet, expected: dict[str, Any]
) -> str:
    candidates: list[tuple[str, Path]] = [
        ("live", live_assets_path(paths)),
        ("old", old_assets_path(paths)),
    ]
    present: list[str] = []
    for name, path in candidates:
        if path.exists():
            try:
                verify_tree(
                    path,
                    expected,
                    strict_regular=False,
                    compare_identity=True,
                )
            except RestoreFailure:
                continue
            present.append(name)
    if expected.get("present"):
        if len(present) != 1:
            raise RestoreFailure(
                "RESTORE_GROUP_CONFLICT", "recovery", "旧资产目录位置或身份不唯一"
            )
        return present[0]
    if present:
        raise RestoreFailure(
            "RESTORE_GROUP_CONFLICT", "recovery", "旧资产目录不应存在"
        )
    return "absent"


def locate_old_group(paths: RestorePathSet, old: dict[str, Any]) -> dict[str, Any]:
    locations: dict[str, str] = {}
    for name in DB_COMPONENTS:
        locations[name], _ = _locate_old_db(paths, name, old["db"][name])
    locations["assets"] = _locate_old_assets(paths, old["assets"])
    return locations


def _locate_new_assets(
    paths: RestorePathSet, expected: dict[str, Any]
) -> str:
    candidates = [
        ("prepared", prepared_assets_path(paths)),
        ("live", live_assets_path(paths)),
    ]
    present: list[str] = []
    for name, path in candidates:
        if path.exists():
            try:
                verify_tree(
                    path,
                    expected,
                    strict_regular=True,
                    compare_identity=True,
                )
            except RestoreFailure:
                continue
            present.append(name)
    if len(present) != 1:
        raise RestoreFailure(
            "RESTORE_GROUP_CONFLICT", "recovery", "新资产目录位置或身份不唯一"
        )
    return present[0]


def locate_new_group(paths: RestorePathSet, new: dict[str, Any]) -> dict[str, Any]:
    expected_db = new["db"]
    candidates = {
        "prepared": file_identity(prepared_db_path(paths)).as_dict(),
        "live": file_identity(live_db_path(paths, _MAIN_DB)).as_dict(),
    }
    present = [key for key, value in candidates.items() if value["present"]]
    matches = [key for key in present if _same_identity(candidates[key], expected_db)]
    if len(matches) != 1:
        raise RestoreFailure(
            "RESTORE_GROUP_CONFLICT", "recovery", "新数据库位置或身份不唯一"
        )
    return {
        "db": matches[0],
        "assets": _locate_new_assets(paths, new["assets"]),
    }


def old_group_complete(paths: RestorePathSet, old: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return locate_old_group(paths, old)
    except RestoreFailure:
        return None


def new_group_complete(paths: RestorePathSet, new: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return locate_new_group(paths, new)
    except RestoreFailure:
        return None


def live_group_state(
    paths: RestorePathSet, old: dict[str, Any], new: dict[str, Any]
) -> dict[str, bool]:
    """Classify the live group from actual identities, not an in-memory flag."""
    old_live = True
    for name in DB_COMPONENTS:
        expected = (old.get("db") or {}).get(name)
        actual = file_identity(live_db_path(paths, name)).as_dict()
        if expected is None:
            if actual.get("present"):
                old_live = False
            continue
        if not _same_identity(actual, expected):
            old_live = False
    expected_assets = old.get("assets")
    if expected_assets:
        try:
            verify_tree(
                live_assets_path(paths),
                expected_assets,
                strict_regular=False,
                compare_identity=True,
            )
        except RestoreFailure:
            old_live = False
    elif live_assets_path(paths).exists():
        old_live = False
    new_live = True
    try:
        if not new.get("db") or not _same_identity(
            file_identity(live_db_path(paths, _MAIN_DB)).as_dict(), new["db"]
        ):
            new_live = False
        if new_live and new.get("assets"):
            verify_tree(
                live_assets_path(paths),
                new["assets"],
                strict_regular=True,
                compare_identity=True,
            )
        elif new_live:
            new_live = False
    except RestoreFailure:
        new_live = False
    return {
        "old_live": old_live,
        "new_live": new_live,
        "changed": (not old_live) or new_live,
    }


def move_live_component_to_old(
    paths: RestorePathSet, name: str
) -> None:
    source = live_db_path(paths, name)
    if not source.exists():
        return
    move_no_replace(source, old_db_path(paths, name), private_parent=True)


def move_old_component_to_live(
    paths: RestorePathSet, name: str
) -> None:
    source = old_db_path(paths, name)
    if not source.exists():
        return
    move_no_replace(source, live_db_path(paths, name), private_parent=False)


def move_live_assets_to_old(paths: RestorePathSet) -> None:
    source = live_assets_path(paths)
    if not source.exists():
        return
    move_no_replace(source, old_assets_path(paths), private_parent=True)


def move_old_assets_to_live(paths: RestorePathSet) -> None:
    source = old_assets_path(paths)
    if not source.exists():
        return
    move_no_replace(source, live_assets_path(paths), private_parent=False)


def move_prepared_assets_to_live(paths: RestorePathSet) -> None:
    source = prepared_assets_path(paths)
    move_no_replace(source, live_assets_path(paths), private_parent=False)


def move_live_assets_to_prepared(paths: RestorePathSet) -> None:
    source = live_assets_path(paths)
    if not source.exists():
        return
    move_no_replace(source, prepared_assets_path(paths), private_parent=True)


def move_prepared_db_to_live(paths: RestorePathSet) -> None:
    move_no_replace(
        prepared_db_path(paths), live_db_path(paths, _MAIN_DB), private_parent=False
    )


def move_live_db_to_prepared(paths: RestorePathSet) -> None:
    source = live_db_path(paths, _MAIN_DB)
    if not source.exists():
        return
    move_no_replace(
        source, prepared_db_path(paths), private_parent=True
    )


def rollback_to_old(paths: RestorePathSet, new: dict[str, Any]) -> None:
    """Move a partially installed new group aside, then restore old exactly."""
    live_db = file_identity(live_db_path(paths, _MAIN_DB)).as_dict()
    if new.get("db") and _same_identity(live_db, new["db"]):
        move_live_db_to_prepared(paths)
    live_assets = live_assets_path(paths)
    if live_assets.exists() and new.get("assets"):
        try:
            verify_tree(
                live_assets,
                new["assets"],
                strict_regular=True,
                compare_identity=True,
            )
        except RestoreFailure:
            pass
        else:
            move_live_assets_to_prepared(paths)
    for name in DB_COMPONENTS:
        move_old_component_to_live(paths, name)
    move_old_assets_to_live(paths)


def _remove_empty_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        side = db_path.with_name(db_path.name + suffix)
        try:
            if side.exists() and side.stat().st_size == 0:
                side.unlink()
        except OSError:
            pass


def verify_installed_group(
    paths: RestorePathSet, new: dict[str, Any], scratch_dir: Path
) -> None:
    ensure_private_dir(scratch_dir)
    db_path = live_db_path(paths, _MAIN_DB)
    current = file_identity(db_path).as_dict()
    if not _same_identity(current, new["db"]):
        raise RestoreFailure(
            "RESTORE_INSTALLED_HASH", "verify", "安装后数据库 hash 不一致"
        )
    backup_validate.validate_database(
        db_path,
        migrate_old=False,
        require_current=True,
        scratch_dir=scratch_dir,
    )
    assets_guard = backup_fs.DirectoryGuard(live_assets_path(paths))
    assets_guard.__enter__()
    try:
        verify_tree(
            live_assets_path(paths),
            new["assets"],
            strict_regular=True,
            compare_identity=True,
        )
    finally:
        assets_guard.close()
    _remove_empty_sidecars(db_path)
