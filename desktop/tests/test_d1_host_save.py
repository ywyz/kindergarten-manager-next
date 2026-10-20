"""D1 restricted host save: operation-id binding, atomic replace, results.

R13: success samples use a real (minimal) DOCX archive; a payload that merely
starts with ``PK`` or lacks required Word parts is refused before the atomic
replace. R11: native saves are globally mutually exclusive across operation
ids. R12: only the agreed endpoints are exposed through pywebview's recursive
js_api discovery, and business endpoints require the completed handshake.
"""

import base64
import inspect
import io
import os
import threading
import time
import uuid
import zipfile

import pytest

import d1_host_api
from d1_host_api import D1HostApi, write_docx_atomic

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def minimal_docx(text: str = "验证内容") -> bytes:
    """A real, minimal DOCX archive (required Word parts, CRC-checkable)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


DOCX_BYTES = minimal_docx()
DOCX_BYTES_OTHER = minimal_docx("另一个文档")
PK_ONLY_FAKE = b"PK-not-a-zip-or-docx"
# The regression payload from the review: 20 bytes starting with PK.
SHORT_PK_FIXTURE = b"PK" + b"x" * 18


def make_api(tmp_path, *, verify=False, dialog_result=None, dialog_calls=None):
    class FakeWindow:
        def create_file_dialog(self, *args, **kwargs):
            if dialog_calls is not None:
                dialog_calls.append(kwargs)
            return dialog_result

    api = D1HostApi(
        launch_token="token",
        window_getter=lambda: FakeWindow(),
        verify_save_dir=(tmp_path / "verify" if verify else None),
    )
    api.page_ready({"bridge_protocol": 1})
    return api


def payload(request_id=None, filename="日计划.docx", data=DOCX_BYTES):
    return {
        "request_id": request_id or uuid.uuid4().hex,
        "filename": filename,
        "payload_base64": base64.b64encode(data).decode(),
    }


class TestSaveDocx:
    def test_dialog_saved_real_file_and_result_cache(self, tmp_path):
        target = tmp_path / "另存为.docx"
        calls = []
        api = make_api(tmp_path, dialog_result=str(target), dialog_calls=calls)
        request_id = uuid.uuid4().hex
        result = api.save_docx(payload(request_id))
        assert result["status"] == "saved"
        assert result["filename"] == "另存为.docx"
        saved = target.read_bytes()
        assert saved == DOCX_BYTES
        # The saved file is a readable DOCX archive with the required parts.
        with zipfile.ZipFile(io.BytesIO(saved)) as archive:
            names = set(archive.namelist())
            assert "[Content_Types].xml" in names
            assert "word/document.xml" in names
        assert len(calls) == 1
        # Same operation id + same payload: cached, no second dialog.
        again = api.save_docx(payload(request_id))
        assert again["status"] == "saved"
        assert len(calls) == 1
        # Read-only result query never writes.
        queried = api.get_save_result({"request_id": request_id})
        assert queried["status"] == "saved"

    def test_same_request_id_different_payload_conflicts(self, tmp_path):
        target = tmp_path / "x.docx"
        api = make_api(tmp_path, dialog_result=str(target))
        request_id = uuid.uuid4().hex
        assert api.save_docx(payload(request_id))["status"] == "saved"
        conflict = api.save_docx(payload(request_id, data=DOCX_BYTES_OTHER))
        assert conflict["status"] == "failed"
        assert conflict["code"] == "SAVE_REQUEST_CONFLICT"
        assert target.read_bytes() == DOCX_BYTES

    def test_canceled_dialog_never_claims_saved(self, tmp_path):
        api = make_api(tmp_path, dialog_result=None)
        request_id = uuid.uuid4().hex
        result = api.save_docx(payload(request_id))
        assert result == {"status": "canceled"}
        assert api.get_save_result({"request_id": request_id})["status"] == "canceled"

    def test_invalid_payloads(self, tmp_path):
        api = make_api(tmp_path, dialog_result=str(tmp_path / "x.docx"))
        bad_b64 = payload()
        bad_b64["payload_base64"] = "!!!not-base64!!!"
        assert api.save_docx(bad_b64)["code"] == "INVALID_PAYLOAD"

        empty = payload()
        empty["payload_base64"] = base64.b64encode(b"").decode()
        assert api.save_docx(empty)["code"] == "INVALID_PAYLOAD"

        non_docx = payload(data=b"not-a-zip")
        assert api.save_docx(non_docx)["code"] == "INVALID_PAYLOAD"

        missing_id = payload()
        missing_id["request_id"] = ""
        assert api.save_docx(missing_id)["code"] == "INVALID_PAYLOAD"

    def test_pk_prefixed_fake_is_rejected_before_any_write(self, tmp_path):
        # R13: the review's 20-byte PK-prefixed payload used to be written and
        # reported saved; it must now be refused before the dialog/write.
        target = tmp_path / "target.docx"
        target.write_bytes(b"OLD-ORIGINAL")
        calls = []
        api = make_api(tmp_path, dialog_result=str(target), dialog_calls=calls)
        for data in (SHORT_PK_FIXTURE, PK_ONLY_FAKE):
            result = api.save_docx(payload(data=data))
            assert result["status"] == "failed", result
            assert result["code"] == "INVALID_PAYLOAD", result
        assert calls == [], "no dialog for an invalid DOCX"
        assert target.read_bytes() == b"OLD-ORIGINAL"

    def test_zip_without_word_parts_is_rejected(self, tmp_path):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "not a docx")
        target = tmp_path / "keep.docx"
        target.write_bytes(b"OLD-ORIGINAL")
        calls = []
        api = make_api(tmp_path, dialog_result=str(target), dialog_calls=calls)
        result = api.save_docx(payload(data=buffer.getvalue()))
        assert result["status"] == "failed"
        assert result["code"] == "INVALID_PAYLOAD"
        assert "缺少必要部件" in result["message"]
        assert calls == []
        assert target.read_bytes() == b"OLD-ORIGINAL"

    def test_truncated_zip_is_rejected(self, tmp_path):
        api = make_api(tmp_path, verify=True)
        truncated = DOCX_BYTES[: len(DOCX_BYTES) // 2]
        result = api.save_docx(payload(data=truncated))
        assert result["status"] == "failed"
        assert result["code"] == "INVALID_PAYLOAD"

    def test_zip_with_empty_xml_parts_is_rejected(self, tmp_path):
        # R13 follow-up: the review's ZIP with empty [Content_Types].xml and
        # word/document.xml used to be written and reported saved; the XML
        # parts must be non-empty before the dialog/replace.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", b"")
            archive.writestr("word/document.xml", b"")
        target = tmp_path / "empty-parts.docx"
        target.write_bytes(b"OLD-ORIGINAL")
        calls = []
        api = make_api(tmp_path, dialog_result=str(target), dialog_calls=calls)
        result = api.save_docx(payload(data=buffer.getvalue()))
        assert result["status"] == "failed"
        assert result["code"] == "INVALID_PAYLOAD"
        assert "为空" in result["message"]
        assert calls == [], "no dialog for an empty-parts ZIP"
        assert target.read_bytes() == b"OLD-ORIGINAL"

    def test_zip_with_broken_xml_is_rejected(self, tmp_path):
        for part in ("[Content_Types].xml", "word/document.xml"):
            parts = {
                "[Content_Types].xml": _CONTENT_TYPES,
                "word/document.xml": (
                    '<?xml version="1.0"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                    'wordprocessingml/2006/main"><w:body></w:document>'
                ),
            }
            parts[part] = "<not-valid-xml"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, text in parts.items():
                    archive.writestr(name, text)
            target = tmp_path / "broken.docx"
            target.write_bytes(b"OLD-ORIGINAL")
            calls = []
            api = make_api(tmp_path, dialog_result=str(target), dialog_calls=calls)
            result = api.save_docx(payload(data=buffer.getvalue()))
            assert result["status"] == "failed", part
            assert result["code"] == "INVALID_PAYLOAD", part
            assert "不是有效 XML" in result["message"], part
            assert calls == [], part
            assert target.read_bytes() == b"OLD-ORIGINAL", part

    def test_zip_with_wrong_xml_roots_is_rejected(self, tmp_path):
        cases = {
            "[Content_Types].xml": (
                '<?xml version="1.0"?><NotTypes xmlns="http://example.com/x"/>',
                "{Content_Types}",
            ),
            "word/document.xml": (
                '<?xml version="1.0"?>'
                '<document xmlns="http://example.com/other"/>',
                "{document}",
            ),
        }
        for part, (text, _label) in cases.items():
            parts = {
                "[Content_Types].xml": _CONTENT_TYPES,
                "word/document.xml": (
                    '<?xml version="1.0"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                    'wordprocessingml/2006/main"><w:body/></w:document>'
                ),
            }
            parts[part] = text
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, value in parts.items():
                    archive.writestr(name, value)
            target = tmp_path / "wrong-root.docx"
            target.write_bytes(b"OLD-ORIGINAL")
            calls = []
            api = make_api(tmp_path, dialog_result=str(target), dialog_calls=calls)
            result = api.save_docx(payload(data=buffer.getvalue()))
            assert result["status"] == "failed", part
            assert result["code"] == "INVALID_PAYLOAD", part
            assert "根元素不正确" in result["message"], part
            assert calls == [], part
            assert target.read_bytes() == b"OLD-ORIGINAL", part

    def test_real_minimal_docx_still_accepted(self, tmp_path):
        # The bounded XML/root check must keep accepting a real DOCX.
        api = make_api(tmp_path, verify=True)
        result = api.save_docx(payload(data=minimal_docx("真实内容")))
        assert result["status"] == "saved"

    def test_save_docx_requires_completed_handshake(self, tmp_path):
        # R12: business endpoints only accept the trusted page that finished
        # the protocol handshake.
        calls = []

        class FakeWindow:
            def create_file_dialog(self, *args, **kwargs):
                calls.append(kwargs)
                return None

        api = D1HostApi(
            launch_token="token",
            window_getter=lambda: FakeWindow(),
            verify_save_dir=None,
        )
        result = api.save_docx(payload())
        assert result["status"] == "failed"
        assert result["code"] == "BRIDGE_NOT_READY"
        assert api.get_save_result({"request_id": "x"}) == {
            "status": "unknown",
            "code": "BRIDGE_NOT_READY",
        }
        assert calls == []
        # After the handshake the same call proceeds normally.
        api.page_ready({"bridge_protocol": 1})
        api._verify_save_dir = tmp_path
        assert api.save_docx(payload())["status"] == "saved"

    def test_payload_too_large_rejected_before_dialog(self, tmp_path):
        calls = []
        api = make_api(tmp_path, dialog_result=str(tmp_path / "x.docx"), dialog_calls=calls)
        oversized = {
            "request_id": uuid.uuid4().hex,
            "filename": "big.docx",
            "payload_base64": "A" * (30 * 1024 * 1024 * 4 // 3 + 2048),
        }
        result = api.save_docx(oversized)
        assert result["status"] == "failed"
        assert result["code"] == "PAYLOAD_TOO_LARGE"
        assert calls == []

    def test_unknown_request_query_never_writes(self, tmp_path):
        api = make_api(tmp_path, dialog_result=None)
        assert api.get_save_result({"request_id": "missing"})["status"] == "unknown"

    def test_suffix_enforced_and_chinese_filename_kept(self, tmp_path):
        api = make_api(tmp_path, verify=True)
        # filename without .docx gets the suffix added by the host.
        result = api.save_docx(payload(filename="计划名", data=DOCX_BYTES))
        assert result["status"] == "saved"
        saved = list((tmp_path / "verify").iterdir())
        assert [path.name for path in saved] == ["计划名.docx"]
        assert saved[0].read_bytes() == DOCX_BYTES

    @pytest.mark.skipif(os.name != "nt", reason="Windows file-lock semantics")
    def test_occupied_target_fails_then_retry_succeeds(self, tmp_path):
        api = make_api(tmp_path, verify=True)
        target = tmp_path / "verify" / "占用.docx"
        (tmp_path / "verify").mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"OLD-ORIGINAL")
        request_id = uuid.uuid4().hex
        with open(target, "rb"):
            # An open handle without delete-share blocks os.replace.
            first = api.save_docx(payload(request_id, filename="占用.docx"))
            assert first["status"] == "failed"
            assert target.read_bytes() == b"OLD-ORIGINAL"
        # The failed attempt releases its operation id only for a NEW id
        # retry by the user; retry with the same id + same payload returns
        # the cached failure and the user then issues a new operation.
        cached = api.save_docx(payload(request_id, filename="占用.docx"))
        assert cached["status"] == "failed"
        retry_id = uuid.uuid4().hex
        second = api.save_docx(payload(retry_id, filename="占用.docx"))
        assert second["status"] == "saved"
        assert target.read_bytes() == DOCX_BYTES
        stray = [p.name for p in (tmp_path / "verify").iterdir() if p.name.endswith(".tmp")]
        assert stray == []


class TestGlobalExclusion:
    def test_different_ids_run_one_native_save_at_a_time(self, tmp_path, monkeypatch):
        # R11: a second operation id waits for the first instead of opening a
        # second dialog/write concurrently.
        state = {"active": 0, "max": 0, "calls": 0}
        guard = threading.Lock()

        def fake_perform(self, filename, data):
            with guard:
                state["active"] += 1
                state["calls"] += 1
                state["max"] = max(state["max"], state["active"])
            time.sleep(0.15)
            with guard:
                state["active"] -= 1
            return {"status": "saved", "filename": filename, "bytes": len(data)}

        monkeypatch.setattr(D1HostApi, "_perform_save", fake_perform)
        api = make_api(tmp_path)
        results = {}

        def run(request_id):
            results[request_id] = api.save_docx(payload(request_id))

        threads = [
            threading.Thread(target=run, args=(uuid.uuid4().hex,)) for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert state["max"] == 1, "native saves overlapped"
        assert state["calls"] == 2
        assert len(results) == 2
        assert all(result["status"] == "saved" for result in results.values())

    def test_same_id_inflight_returns_pending_other_payload_conflicts(
        self, tmp_path, monkeypatch
    ):
        gate = threading.Event()

        def fake_perform(self, filename, data):
            gate.wait(timeout=10)
            return {"status": "saved", "filename": filename, "bytes": len(data)}

        monkeypatch.setattr(D1HostApi, "_perform_save", fake_perform)
        api = make_api(tmp_path)
        request_id = uuid.uuid4().hex
        first_result = {}

        def run():
            first_result.update(api.save_docx(payload(request_id)))

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.time() + 5
        while not api._save_in_progress() and time.time() < deadline:
            time.sleep(0.01)
        assert api._save_in_progress()
        # Same id + same payload: shared result, still pending.
        assert api.save_docx(payload(request_id)) == {"status": "pending"}
        assert api.get_save_result({"request_id": request_id})["status"] == "pending"
        # Same id + different payload: refused without touching the first.
        conflict = api.save_docx(payload(request_id, data=DOCX_BYTES_OTHER))
        assert conflict["code"] == "SAVE_REQUEST_CONFLICT"
        gate.set()
        thread.join(timeout=10)
        assert first_result["status"] == "saved"
        assert api.get_save_result({"request_id": request_id})["status"] == "saved"

    def test_save_in_progress_probe_tracks_inflight_operations(
        self, tmp_path, monkeypatch
    ):
        gate = threading.Event()
        monkeypatch.setattr(
            D1HostApi,
            "_perform_save",
            lambda self, filename, data: (
                gate.wait(timeout=10),
                {"status": "saved", "filename": filename, "bytes": len(data)},
            )[1],
        )
        api = make_api(tmp_path)
        assert api._save_in_progress() is False
        thread = threading.Thread(target=lambda: api.save_docx(payload()))
        thread.start()
        deadline = time.time() + 5
        while not api._save_in_progress() and time.time() < deadline:
            time.sleep(0.01)
        assert api._save_in_progress() is True
        gate.set()
        thread.join(timeout=10)
        assert api._save_in_progress() is False


class TestBridgeSurface:
    @staticmethod
    def pywebview_exposed_names(api) -> set[str]:
        """Replicate pywebview's recursive js_api discovery rule."""
        exposed_objects: list[int] = []
        functions: dict[str, object] = {}

        def collect(obj, base_name=""):
            object_id = id(obj)
            if object_id in exposed_objects:
                return
            exposed_objects.append(object_id)
            for name in dir(obj):
                try:
                    full_name = f"{base_name}.{name}" if base_name else name
                    if name.startswith("_"):
                        continue
                    attr = getattr(obj, name)
                    if not getattr(attr, "_serializable", True):
                        continue
                    if inspect.ismethod(attr) or inspect.isfunction(attr):
                        functions[full_name] = attr
                    elif inspect.isclass(attr) or (
                        isinstance(attr, object)
                        and not callable(attr)
                        and hasattr(attr, "__module__")
                    ):
                        collect(attr, full_name)
                except Exception:
                    continue

        collect(api)
        return set(functions)

    def test_exposed_endpoints_are_exactly_the_agreed_set(self, tmp_path):
        api = make_api(tmp_path)
        # Give the real coordinator the recursive exposure would otherwise
        # reach; it must stay private.
        api._close_coordinator = d1_host_api.CloseCoordinator(
            notify_page=lambda request_id, generation=None: None,
            destroy_window=lambda: None,
            notify_aborted=lambda request_id, reason: None,
        )
        assert (
            self.pywebview_exposed_names(api)
            == set(d1_host_api.BRIDGE_ALLOWED_ENDPOINTS)
        )
        # No underscore-free attribute besides the agreed endpoint methods.
        public_attributes = {
            name for name in dir(api) if not name.startswith("_")
        }
        assert public_attributes == set(d1_host_api.BRIDGE_ALLOWED_ENDPOINTS)
        # The notification helpers are private.
        assert not hasattr(api, "notify_request_close")
        assert not hasattr(api, "notify_close_aborted")
        assert not hasattr(api, "close_coordinator")


class TestAtomicWrite:
    def test_commit_point_distinction_after_replace_is_unknown(
        self, tmp_path, monkeypatch
    ):
        target = tmp_path / "atomic.docx"
        original_stat = d1_host_api.Path.stat
        replaced = {"done": False}
        original_replace = d1_host_api.os.replace

        def tracking_replace(src, dst):
            original_replace(src, dst)
            replaced["done"] = True

        def failing_stat(self, *args, **kwargs):
            if replaced["done"] and str(self) == str(target):
                raise OSError("stat failed after commit")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(d1_host_api.os, "replace", tracking_replace)
        monkeypatch.setattr(d1_host_api.Path, "stat", failing_stat)
        result = write_docx_atomic(str(target), DOCX_BYTES)
        assert result["status"] == "unknown"
        # R16: the post-commit verification failure stays unknown (never
        # "failed", never "the old target is unchanged") and its reason is
        # desensitized.
        assert result["code"] == "SAVE_RESULT_UNKNOWN"
        assert "无法确认" in result["message"]
        assert str(target) not in result["message"]
        assert "stat failed after commit" not in result["message"]
        assert ".tmp" not in result["message"]
        # The target was actually replaced; no temp files remain.
        assert target.read_bytes() == DOCX_BYTES
        assert [p.name for p in tmp_path.iterdir()] == ["atomic.docx"]

    def test_failure_before_commit_keeps_original(self, tmp_path, monkeypatch):
        target = tmp_path / "keep.docx"
        target.write_bytes(b"OLD-ORIGINAL")

        def boom(src, dst):
            raise OSError("replace failed")

        monkeypatch.setattr(d1_host_api.os, "replace", boom)
        result = write_docx_atomic(str(target), DOCX_BYTES)
        assert result["status"] == "failed"
        assert target.read_bytes() == b"OLD-ORIGINAL"
        assert [p.name for p in tmp_path.iterdir()] == ["keep.docx"]

    def test_suffix_rule_shared(self, tmp_path):
        result = write_docx_atomic(str(tmp_path / "x.txt"), DOCX_BYTES)
        assert result["status"] == "failed"
        assert result["code"] == "INVALID_TARGET"
        assert list(tmp_path.iterdir()) == []


class TestFailureDesensitization:
    """R16: every outward save-failure boundary returns a stable reason with
    no absolute path, temporary name or original exception detail."""

    _BASE_LEAK_TOKENS = (
        ".tmp",
        "WinError",
        "winerror",
        "Errno",
        "PermissionError",
        "RuntimeError",
        "Traceback",
    )

    @classmethod
    def _assert_desensitized(cls, result: dict, tmp_path, *extra_tokens: str) -> None:
        text = " ".join(
            str(result.get(field) or "") for field in ("message", "code", "filename")
        )
        for token in (*cls._BASE_LEAK_TOKENS, str(tmp_path), *extra_tokens):
            assert token not in text, (token, result)

    @pytest.mark.skipif(os.name != "nt", reason="Windows file-lock semantics")
    def test_occupied_target_first_response_and_cache_desensitized(self, tmp_path):
        api = make_api(tmp_path, verify=True)
        target = tmp_path / "verify" / "占用目标.docx"
        (tmp_path / "verify").mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"OLD-ORIGINAL")
        request_id = uuid.uuid4().hex
        with open(target, "rb"):
            first = api.save_docx(payload(request_id, filename="占用目标.docx"))
        # A stable occupancy reason, never the path/temp/exception text.
        assert first["status"] == "failed"
        assert first["code"] == "SAVE_TARGET_IN_USE"
        assert "占用" in first["message"]
        self._assert_desensitized(first, tmp_path, target.name)
        # The cached read-only result answers with the same desensitized
        # reason; no side effect on the old target.
        cached = api.get_save_result({"request_id": request_id})
        assert cached.get("status") == "failed"
        assert cached.get("code") == "SAVE_TARGET_IN_USE"
        assert cached.get("message") == first["message"]
        assert target.read_bytes() == b"OLD-ORIGINAL"
        # Same id + same payload returns the cached failure unchanged.
        again = api.save_docx(payload(request_id, filename="占用目标.docx"))
        assert again["message"] == first["message"]
        # After the handle is released a NEW operation id saves normally.
        retry = api.save_docx(payload(filename="占用目标.docx"))
        assert retry["status"] == "saved"
        assert target.read_bytes() == DOCX_BYTES

    def test_dialog_failure_reason_desensitized(self, tmp_path):
        class BrokenWindow:
            def create_file_dialog(self, *args, **kwargs):
                raise RuntimeError(f"dialog exploded at {tmp_path / 'secret.docx'}")

        api = D1HostApi(
            launch_token="token",
            window_getter=lambda: BrokenWindow(),
            verify_save_dir=None,
        )
        api.page_ready({"bridge_protocol": 1})
        result = api.save_docx(payload())
        assert result["status"] == "failed"
        assert result["code"] == "SAVE_DIALOG_FAILED"
        assert "对话框" in result["message"]
        self._assert_desensitized(result, tmp_path, "exploded", "secret.docx")

    def test_inner_fallback_reason_desensitized(self, tmp_path, monkeypatch):
        def boom(self, filename, data):
            raise RuntimeError(f"synthetic boom at {tmp_path / 'x.docx'} temp.tmp")

        monkeypatch.setattr(D1HostApi, "_perform_save", boom)
        api = make_api(tmp_path)
        result = api.save_docx(payload())
        assert result["status"] == "failed"
        assert result["code"] == "SAVE_FAILED"
        self._assert_desensitized(result, tmp_path, "synthetic", "boom", "x.docx")

    def test_outermost_bridge_fallback_reason_desensitized(self, tmp_path, monkeypatch):
        def boom(self, payload):
            raise RuntimeError(f"outer boom at {tmp_path / 'y.docx'} .tmp")

        monkeypatch.setattr(D1HostApi, "_save_docx_inner", boom)
        api = make_api(tmp_path)
        result = api.save_docx(payload())
        assert result["status"] == "failed"
        assert result["code"] == "SAVE_FAILED"
        self._assert_desensitized(result, tmp_path, "outer", "boom", "y.docx")

    def test_broken_xml_reason_has_no_parser_detail(self, tmp_path):
        parts = {
            "[Content_Types].xml": _CONTENT_TYPES,
            "word/document.xml": (
                '<?xml version="1.0"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body></w:document>'
            ),
        }
        parts["word/document.xml"] = "<not-valid-xml"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, text in parts.items():
                archive.writestr(name, text)
        api = make_api(tmp_path, verify=True)
        result = api.save_docx(payload(data=buffer.getvalue()))
        assert result["status"] == "failed"
        assert result["code"] == "INVALID_PAYLOAD"
        # The fixed format only: no parser position/details from the original
        # exception.
        assert result["message"] == "DOCX 必要部件不是有效 XML：word/document.xml"
        self._assert_desensitized(result, tmp_path, "line", "column", "not well-formed")


class TestBridge:
    def test_bootstrap_and_page_ready_protocol(self, tmp_path):
        api = make_api(tmp_path)
        bootstrap = api.get_bootstrap()
        assert bootstrap["bridge_protocol"] == 1
        assert bootstrap["launch_token"] == "token"
        assert api.page_ready({"bridge_protocol": 2}) == {
            "accepted": False,
            "host_protocol": 1,
        }
        # complete_close before page_ready is refused.
        assert api.complete_close({"close_request_id": "x", "allow": True}) == {
            "accepted": False,
            "state": "unknown",
        }
        assert api.page_ready({"bridge_protocol": 1}) == {
            "accepted": True,
            "host_protocol": 1,
        }
        # page_ready is idempotent for the same protocol.
        assert api.page_ready({"bridge_protocol": 1}) == {
            "accepted": True,
            "host_protocol": 1,
        }
