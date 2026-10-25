"""Source-only U3 harness configuration.

The product update entry never reads this file.  A dedicated U3 selftest phase
uses it to provide an isolated release source, install root and new-app command
without adding URL/path/command/public-key switches to the page or product
configuration.  Frozen runs reject these phases.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from update_trust import ReleaseConfigError, ReleaseSource


class U3ConfigError(RuntimeError):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise U3ConfigError("U3 配置无法读取") from exc
    if not isinstance(data, dict):
        raise U3ConfigError("U3 配置必须是对象")
    required = {
        "release_source",
        "install_root",
        "app_dir",
        "staging_root",
        "helper_command",
        "new_app_command",
    }
    if not required.issubset(data) or not set(data) <= required | {"release_config"}:
        raise U3ConfigError("U3 配置字段不合法")
    source = data.get("release_source")
    if not isinstance(source, dict):
        raise U3ConfigError("U3 release_source 不合法")
    if not isinstance(data.get("helper_command"), list) or not all(
        isinstance(item, str) and item for item in data["helper_command"]
    ):
        raise U3ConfigError("U3 helper_command 不合法")
    if not isinstance(data.get("new_app_command"), list) or not all(
        isinstance(item, str) and item for item in data["new_app_command"]
    ):
        raise U3ConfigError("U3 new_app_command 不合法")
    return data


def release_source(config: dict[str, Any]) -> ReleaseSource:
    raw = dict(config["release_source"])
    keys = raw.get("public_keys")
    if not isinstance(keys, dict) or not keys:
        raise U3ConfigError("U3 测试信任表为空")
    decoded: dict[str, bytes] = {}
    for key_id, value in keys.items():
        if not isinstance(value, str):
            raise U3ConfigError("U3 测试公钥不合法")
        try:
            decoded[str(key_id)] = base64.b64decode(value.encode("ascii"), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise U3ConfigError("U3 测试公钥 base64 不合法") from exc
    ca_value = raw.get("ca_pem_path")
    ca_pem = None
    if ca_value:
        try:
            ca_pem = Path(str(ca_value)).read_text(encoding="utf-8")
        except OSError as exc:
            raise U3ConfigError("U3 测试 CA 无法读取") from exc
    try:
        source = ReleaseSource(
            origin=str(raw.get("origin", "")),
            metadata_path=str(raw.get("metadata_path", "")),
            public_keys=decoded,
            channel=str(raw.get("channel", "stable")),
            ca_pem=ca_pem,
            connect_host=raw.get("connect_host"),
            server_hostname=raw.get("server_hostname"),
            test_only=True,
        )
        source.validate()
    except ReleaseConfigError as exc:
        raise U3ConfigError(str(exc)) from exc
    return source
