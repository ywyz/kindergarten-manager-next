"""R8: WebView2 detection must accept system and per-user installs.

Per-user installs live under HKCU ``Software\\Microsoft\\EdgeUpdate`` while a
system install on 64-bit Windows lives under
HKLM ``Software\\WOW6432Node\\...``. The detection is exercised with an
injected registry reader so no real hive is touched.
"""

import d0_main

VERSION = "154.0.4258.62"
GUID = d0_main.WEBVIEW2_CLIENT_GUID


def _reader(mapping):
    def read(root_name, subkey):
        try:
            return mapping[(root_name, subkey)]
        except KeyError:
            raise FileNotFoundError(subkey)

    return read


def _missing(root_name, subkey):
    raise FileNotFoundError(subkey)


def test_per_user_install_detected():
    key = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}"
    reader = _reader({("HKEY_CURRENT_USER", key): VERSION})
    assert d0_main.webview2_runtime_version(reader) == VERSION


def test_system_wow6432_install_detected():
    key = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID}"
    reader = _reader({("HKEY_LOCAL_MACHINE", key): VERSION})
    assert d0_main.webview2_runtime_version(reader) == VERSION


def test_system_64bit_path_detected():
    key = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}"
    reader = _reader({("HKEY_LOCAL_MACHINE", key): VERSION})
    assert d0_main.webview2_runtime_version(reader) == VERSION


def test_missing_returns_none():
    assert d0_main.webview2_runtime_version(_missing) is None


def test_zero_version_is_treated_as_missing():
    key = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}"
    reader = _reader({("HKEY_CURRENT_USER", key): "0.0.0.0"})
    assert d0_main.webview2_runtime_version(reader) is None


def test_candidates_include_per_user_without_wow6432node():
    paths = d0_main.webview2_registry_candidates()
    assert any(
        root == "HKEY_CURRENT_USER" and "WOW6432Node" not in subkey
        for root, subkey in paths
    )


def test_reader_error_does_not_abort_detection():
    def flaky(root_name, subkey):
        if root_name == "HKEY_CURRENT_USER":
            raise OSError("denied")
        key = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID}"
        if subkey == key:
            return VERSION
        raise FileNotFoundError(subkey)

    assert d0_main.webview2_runtime_version(flaky) == VERSION
