"""Signed latest-manifest, channel isolation and cache-request tests.

Pure tests inject fixed trust material directly through
``PackageTrust(source_url=..., keys={...}, channel="stable")``.  The desktop
release path instead fills the ``PACKAGED_*`` constants in
``app.local.prompt_package`` at freeze time, so Codex can reproduce these wire
tests against a temporary HTTPS origin and test key without changing the
source default (which stays unconfigured).
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.local import prompt_package_manifest as manifest_module
from app.local.prompt_bundles import canonical_json
from app.local.prompt_package import (
    PackageTrust,
    PromptPackageError,
    verify_package,
)
from app.local.prompt_package_manifest import (
    PromptManifest,
    manifest_url,
    package_url,
    verify_manifest,
    verify_package_for_manifest,
)
from app.local.prompt_package_service import (
    PromptPackageNetworkError,
    PromptPackageService,
    _NoRedirect,
    fetch_channel_package,
    fetch_signed_manifest,
)
from tests.local.test_prompt_package import _package, _payload


def _manifest(
    private: Ed25519PrivateKey,
    *,
    channel: str,
    sequence: int,
    package_sha256: str,
    key_id: str = "test-key",
) -> bytes:
    unsigned = {
        "format_version": 1,
        "channel": channel,
        "release_sequence": sequence,
        "package_sha256": package_sha256,
        "key_id": key_id,
    }
    signature = private.sign(
        b"kgm-prompt-manifest-v1\n" + canonical_json(unsigned).encode("utf-8")
    )
    document = {
        **unsigned,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return canonical_json(document).encode("utf-8")


def _trust(
    private: Ed25519PrivateKey,
    *,
    channel: str,
    key_id: str = "test-key",
) -> PackageTrust:
    return PackageTrust(
        source_url="https://example.test",
        keys={key_id: private.public_key().public_bytes_raw()},
        client_version="0.1.0",
        channel=channel,
    )


class ManifestVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.package_raw = _package(
            self.private,
            sequence=3,
            payload=_payload(bump={"daily_lesson_split"}, suffix="三"),
        )
        self.package_sha = hashlib.sha256(self.package_raw).hexdigest()
        self.trust = _trust(self.private, channel="stable")

    def test_manifest_and_urls(self) -> None:
        raw = _manifest(
            self.private,
            channel="stable",
            sequence=3,
            package_sha256=self.package_sha,
        )
        manifest = verify_manifest(raw, self.trust)
        self.assertEqual(manifest.channel, "stable")
        self.assertEqual(manifest.release_sequence, 3)
        self.assertEqual(manifest.package_sha256, self.package_sha)
        self.assertEqual(
            manifest_url(self.trust),
            "https://example.test/prompt-packages/stable/latest.json",
        )
        self.assertEqual(
            package_url(self.trust, manifest),
            "https://example.test/prompt-packages/stable/"
            f"v3-{self.package_sha}.json",
        )

    def test_channel_source_is_https_origin_only(self) -> None:
        manifest = PromptManifest(
            channel="stable",
            release_sequence=3,
            package_sha256=self.package_sha,
            key_id="test-key",
            signature="",
            content_sha256="",
        )
        for source in (
            "http://example.test",
            "https://example.test/base",
            "https://example.test/?cache=1",
            "https://example.test#fragment",
            "https://user:password@example.test",
        ):
            trust = PackageTrust(
                source_url=source,
                keys={"test-key": self.private.public_key().public_bytes_raw()},
                client_version="0.1.0",
                channel="stable",
            )
            with self.assertRaises(PromptPackageError) as raised:
                manifest_url(trust)
            self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_INVALID")
            with self.assertRaises(PromptPackageError) as raised:
                package_url(trust, manifest)
            self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_INVALID")

        for source in ("https://example.test", "https://example.test/"):
            trust = PackageTrust(
                source_url=source,
                keys={"test-key": self.private.public_key().public_bytes_raw()},
                client_version="0.1.0",
                channel="stable",
            )
            self.assertEqual(
                manifest_url(trust),
                "https://example.test/prompt-packages/stable/latest.json",
            )
            self.assertEqual(
                package_url(trust, manifest),
                "https://example.test/prompt-packages/stable/"
                f"v3-{self.package_sha}.json",
            )

    def test_manifest_signature_channel_key_and_fields(self) -> None:
        raw = _manifest(
            self.private,
            channel="stable",
            sequence=3,
            package_sha256=self.package_sha,
        )
        verify_manifest(raw, self.trust)
        tampered_doc = json.loads(raw.decode("utf-8"))
        signature = bytearray(base64.b64decode(tampered_doc["signature"]))
        signature[0] ^= 1
        tampered_doc["signature"] = base64.b64encode(bytes(signature)).decode(
            "ascii"
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_manifest(
                canonical_json(tampered_doc).encode("utf-8"), self.trust
            )
        self.assertEqual(
            raised.exception.code, "PACKAGE_MANIFEST_SIGNATURE_INVALID"
        )

        preview = _manifest(
            self.private,
            channel="preview",
            sequence=4,
            package_sha256=self.package_sha,
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_manifest(preview, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_MANIFEST_CHANNEL")

        unknown = _manifest(
            self.private,
            channel="stable",
            sequence=3,
            package_sha256=self.package_sha,
            key_id="unknown",
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_manifest(unknown, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_MANIFEST_KEY_UNKNOWN")

        extra = raw.replace(
            b'"signature":', b'"extra":true,"signature":', 1
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_manifest(extra, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_MANIFEST_INVALID")

        duplicate = raw.replace(
            b'"channel":"stable"',
            b'"channel":"stable","channel":"preview"',
            1,
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_manifest(duplicate, self.trust)
        self.assertEqual(raised.exception.code, "PACKAGE_JSON_INVALID")

    def test_package_manifest_binding(self) -> None:
        raw = _manifest(
            self.private,
            channel="stable",
            sequence=3,
            package_sha256=self.package_sha,
        )
        manifest = verify_manifest(raw, self.trust)
        package = verify_package_for_manifest(
            self.package_raw, manifest, self.trust
        )
        self.assertEqual(package.release_sequence, 3)
        self.assertEqual(package.key_id, "test-key")

        with self.assertRaises(PromptPackageError) as raised:
            verify_package_for_manifest(
                self.package_raw + b" ", manifest, self.trust
            )
        self.assertEqual(raised.exception.code, "PACKAGE_MANIFEST_HASH")

        wrong_sequence = PromptManifest(
            channel="stable",
            release_sequence=4,
            package_sha256=self.package_sha,
            key_id="test-key",
            signature="",
            content_sha256="",
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_package_for_manifest(
                self.package_raw, wrong_sequence, self.trust
            )
        self.assertEqual(raised.exception.code, "PACKAGE_MANIFEST_SEQUENCE")

        other = Ed25519PrivateKey.generate()
        trust_two = PackageTrust(
            source_url="https://example.test",
            keys={
                "test-key": self.private.public_key().public_bytes_raw(),
                "other-key": other.public_key().public_bytes_raw(),
            },
            client_version="0.1.0",
            channel="stable",
        )
        other_manifest = PromptManifest(
            channel="stable",
            release_sequence=3,
            package_sha256=self.package_sha,
            key_id="other-key",
            signature="",
            content_sha256="",
        )
        with self.assertRaises(PromptPackageError) as raised:
            verify_package_for_manifest(
                self.package_raw, other_manifest, trust_two
            )
        self.assertEqual(raised.exception.code, "PACKAGE_MANIFEST_KEY")


class ChannelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="kgm-package-channel-")
        self.root = Path(self.temp.name)
        self.private = Ed25519PrivateKey.generate()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _raw(
        self, sequence: int, suffix: str, *, channel: str = "stable"
    ) -> tuple[bytes, bytes, str]:
        package = _package(
            self.private,
            sequence=sequence,
            payload=_payload(bump={"daily_lesson_split"}, suffix=suffix),
        )
        sha = hashlib.sha256(package).hexdigest()
        manifest = _manifest(
            self.private,
            channel=channel,
            sequence=sequence,
            package_sha256=sha,
        )
        return manifest, package, sha

    def _service(
        self,
        *,
        channel: str,
        manifest: bytes,
        package: bytes,
        calls: list[int],
    ) -> PromptPackageService:
        trust = _trust(self.private, channel=channel)
        return PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=trust,
            manifest_fetcher=lambda _trust: manifest,
            channel_package_fetcher=lambda _trust, _manifest: package,
            apply_func=lambda item: calls.append(item.release_sequence),
        )

    def test_stable_and_preview_have_separate_cache_and_ledger(self) -> None:
        stable_manifest, stable_package, _ = self._raw(3, "stable")
        preview_manifest, preview_package, _ = self._raw(
            4, "preview", channel="preview"
        )
        calls: list[int] = []
        stable = self._service(
            channel="stable",
            manifest=stable_manifest,
            package=stable_package,
            calls=calls,
        )
        preview = self._service(
            channel="preview",
            manifest=preview_manifest,
            package=preview_package,
            calls=calls,
        )
        self.assertEqual(stable.store.root, self.root / ".prompt-packages" / "stable")
        self.assertEqual(preview.store.root, self.root / ".prompt-packages" / "preview")
        self.assertEqual(stable.check(manual=True)["state"], "updated")
        self.assertEqual(preview.check(manual=True)["state"], "updated")
        self.assertEqual(calls, [3, 4])
        self.assertEqual(
            stable.store.read_state()["accepted"]["release_sequence"], 3
        )
        self.assertEqual(
            preview.store.read_state()["accepted"]["release_sequence"], 4
        )
        self.assertEqual(stable.check(manual=True)["state"], "no_update")
        self.assertEqual(calls, [3, 4])

    def test_manifest_binding_errors_do_not_apply(self) -> None:
        manifest, package, sha = self._raw(3, "stable")
        calls: list[int] = []
        service = self._service(
            channel="stable", manifest=manifest, package=package, calls=calls
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")
        self.assertEqual(calls, [3])

        broken = bytearray(package)
        broken[-2] ^= 1
        service = self._service(
            channel="stable", manifest=manifest, package=bytes(broken), calls=calls
        )
        self.assertEqual(service.check(manual=True)["state"], "invalid")
        self.assertEqual(calls, [3])

    def test_stable_keeps_active_when_preview_content_is_offered(self) -> None:
        stable_manifest, stable_package, _ = self._raw(3, "stable")
        preview_manifest, preview_package, _ = self._raw(
            4, "preview", channel="preview"
        )
        calls: list[int] = []
        service = self._service(
            channel="stable",
            manifest=stable_manifest,
            package=stable_package,
            calls=calls,
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")

        service = self._service(
            channel="stable",
            manifest=preview_manifest,
            package=preview_package,
            calls=calls,
        )
        status = service.check(manual=True)
        self.assertEqual(status["state"], "invalid")
        self.assertEqual(status["active_source"], "package")
        self.assertEqual(status["release_sequence"], 3)
        self.assertEqual(calls, [3])
        self.assertEqual(
            service.store.read_state()["accepted"]["release_sequence"], 3
        )
        self.assertFalse((self.root / ".prompt-packages" / "preview").exists())

    def test_manifest_network_failure_keeps_active(self) -> None:
        manifest, package, _ = self._raw(3, "stable")
        calls: list[int] = []
        service = self._service(
            channel="stable", manifest=manifest, package=package, calls=calls
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")

        def offline(_trust):
            raise PromptPackageNetworkError(
                "PACKAGE_OFFLINE", "无法连接提示词包来源"
            )

        service = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            manifest_fetcher=offline,
            channel_package_fetcher=lambda _trust, _manifest: package,
            apply_func=lambda item: calls.append(item.release_sequence),
        )
        status = service.check(manual=True)
        self.assertEqual(status["state"], "offline")
        self.assertEqual(status["active_source"], "package")
        self.assertEqual(status["release_sequence"], 3)
        self.assertEqual(calls, [3])

    def test_offline_restart_uses_stored_signed_manifest(self) -> None:
        manifest, package, _ = self._raw(3, "stable")
        calls: list[int] = []
        service = self._service(
            channel="stable", manifest=manifest, package=package, calls=calls
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")
        active = service.store.read_state()["active"]
        proof = service.store.active_manifest_path.read_bytes()
        self.assertEqual(
            active["manifest_sha256"], hashlib.sha256(proof).hexdigest()
        )

        restarted = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            manifest_fetcher=lambda _trust: (_ for _ in ()).throw(
                AssertionError("offline startup must not fetch the manifest")
            ),
            channel_package_fetcher=lambda *_args: (_ for _ in ()).throw(
                AssertionError("offline startup must not fetch the package")
            ),
            apply_func=lambda item: calls.append(item.release_sequence),
        )
        restarted.startup()
        self.assertEqual(calls, [3, 3])
        self.assertEqual(restarted.status()["active_source"], "package")
        self.assertEqual(
            restarted.store.active_manifest_path.read_bytes(), proof
        )

    def test_channel_cache_without_manifest_proof_fails_closed_then_repairs(
        self,
    ) -> None:
        manifest, package, _ = self._raw(3, "stable")
        calls: list[int] = []
        service = self._service(
            channel="stable", manifest=manifest, package=package, calls=calls
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")
        service.store.active_manifest_path.unlink()
        state = service.store.read_state()
        state["active"].pop("manifest_sha256", None)
        service.store.write_state(state)

        restarted = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            manifest_fetcher=lambda _trust: (_ for _ in ()).throw(
                AssertionError("startup must not fetch after a proof failure")
            ),
            channel_package_fetcher=lambda *_args: (_ for _ in ()).throw(
                AssertionError("startup must not fetch after a proof failure")
            ),
            apply_func=lambda item: calls.append(item.release_sequence),
        )
        restarted.startup()
        self.assertEqual(calls, [3])
        status = restarted.status()
        self.assertEqual(status["state"], "cache_invalid")
        self.assertEqual(status["active_source"], "builtin")
        self.assertTrue(restarted.runtime.prompt_package_builtin_only)

        online = self._service(
            channel="stable", manifest=manifest, package=package, calls=calls
        )
        repaired = online.check(manual=True)
        self.assertEqual(repaired["state"], "no_update")
        self.assertEqual(repaired["active_source"], "package")
        self.assertEqual(repaired["release_sequence"], 3)
        self.assertEqual(calls, [3, 3])
        self.assertTrue(online.store.active_manifest_path.exists())
        self.assertEqual(
            online.store.read_state()["active"]["manifest_sha256"],
            hashlib.sha256(
                online.store.active_manifest_path.read_bytes()
            ).hexdigest(),
        )

    def test_copied_preview_cache_is_not_applied_as_stable(self) -> None:
        preview_manifest, preview_package, _ = self._raw(
            3, "preview", channel="preview"
        )
        preview_calls: list[int] = []
        preview = self._service(
            channel="preview",
            manifest=preview_manifest,
            package=preview_package,
            calls=preview_calls,
        )
        self.assertEqual(preview.check(manual=True)["state"], "updated")
        self.assertEqual(preview_calls, [3])

        applied: list[int] = []
        stable = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            apply_func=lambda item: applied.append(item.release_sequence),
        )
        stable.store.root.mkdir(parents=True, exist_ok=True)
        for item in preview.store.root.iterdir():
            if item.is_file():
                (stable.store.root / item.name).write_bytes(item.read_bytes())
        stable.startup()
        self.assertEqual(applied, [])
        status = stable.status()
        self.assertEqual(status["state"], "cache_invalid")
        self.assertEqual(status["active_source"], "builtin")

    def test_tampered_signed_manifest_proof_fails_closed(self) -> None:
        manifest, package, _ = self._raw(3, "stable")
        calls: list[int] = []
        service = self._service(
            channel="stable", manifest=manifest, package=package, calls=calls
        )
        self.assertEqual(service.check(manual=True)["state"], "updated")
        document = json.loads(
            service.store.active_manifest_path.read_text(encoding="utf-8")
        )
        signature = bytearray(base64.b64decode(document["signature"]))
        signature[0] ^= 1
        document["signature"] = base64.b64encode(bytes(signature)).decode(
            "ascii"
        )
        tampered = canonical_json(document).encode("utf-8")
        service.store.active_manifest_path.write_bytes(tampered)
        state = service.store.read_state()
        state["active"]["manifest_sha256"] = hashlib.sha256(
            tampered
        ).hexdigest()
        service.store.write_state(state)

        restarted = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            apply_func=lambda item: calls.append(item.release_sequence),
        )
        restarted.startup()
        self.assertEqual(calls, [3])
        self.assertEqual(restarted.status()["active_source"], "builtin")
        self.assertEqual(restarted.status()["state"], "cache_invalid")

    def test_pending_channel_package_keeps_manifest_proof(self) -> None:
        manifest, package, _ = self._raw(3, "stable")

        def fail(_package):
            raise RuntimeError("synthetic staging failure")

        first = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            manifest_fetcher=lambda _trust: manifest,
            channel_package_fetcher=lambda *_args: package,
            apply_func=fail,
        )
        self.assertEqual(first.check(manual=True)["state"], "failed")
        pending = first.store.read_state()["pending"]
        proof = first.store.pending_manifest_path.read_bytes()
        self.assertEqual(
            pending["manifest_sha256"], hashlib.sha256(proof).hexdigest()
        )

        applied: list[int] = []
        resumed = PromptPackageService(
            SimpleNamespace(data_dir=self.root),
            trust=_trust(self.private, channel="stable"),
            manifest_fetcher=lambda _trust: (_ for _ in ()).throw(
                AssertionError("pending startup must not fetch the manifest")
            ),
            channel_package_fetcher=lambda *_args: (_ for _ in ()).throw(
                AssertionError("pending startup must not fetch the package")
            ),
            apply_func=lambda item: applied.append(item.release_sequence),
        )
        resumed.startup()
        self.assertEqual(applied, [3])
        self.assertEqual(resumed.status()["active_source"], "package")
        self.assertIsNone(resumed.store.read_state()["pending"])
        self.assertTrue(resumed.store.active_manifest_path.exists())

    def test_manifest_https_and_cache_headers(self) -> None:
        package_raw = _package(self.private, sequence=3)
        sha = hashlib.sha256(package_raw).hexdigest()
        manifest = PromptManifest(
            channel="stable",
            release_sequence=3,
            package_sha256=sha,
            key_id="test-key",
            signature="",
            content_sha256="",
        )
        trust = _trust(self.private, channel="stable")
        requests = []

        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self, _size):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Response()

        with patch(
            "app.local.prompt_package_service.urllib.request.build_opener",
            lambda *_args, **_kwargs: Opener(),
        ):
            fetch_signed_manifest(trust)
            fetch_channel_package(trust, manifest)
        self.assertTrue(requests[0].full_url.endswith("/stable/latest.json"))
        self.assertEqual(
            requests[0].get_header("Cache-control"), "no-cache"
        )
        self.assertTrue(
            requests[1].full_url.endswith(
                f"/stable/v3-{sha}.json"
            )
        )
        self.assertIsNone(requests[1].get_header("Cache-control"))

        with self.assertRaises(PromptPackageNetworkError) as raised:
            fetch_signed_manifest(
                PackageTrust(
                    source_url="http://example.test",
                    keys={"test-key": self.private.public_key().public_bytes_raw()},
                    channel="stable",
                )
            )
        self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_INVALID")

        with self.assertRaises(PromptPackageNetworkError) as raised:
            fetch_signed_manifest(
                PackageTrust(
                    source_url="https://example.test?cache=1",
                    keys={"test-key": self.private.public_key().public_bytes_raw()},
                    channel="stable",
                )
            )
        self.assertEqual(raised.exception.code, "PACKAGE_SOURCE_INVALID")

    def test_redirect_handler_refuses(self) -> None:
        with self.assertRaises(PromptPackageNetworkError):
            _NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://evil.example"
            )


class PackagedTrustTests(unittest.TestCase):
    def test_fixed_channel_and_source_default(self) -> None:
        from app.local import prompt_package as module

        private = Ed25519PrivateKey.generate()
        public_b64 = base64.b64encode(
            private.public_key().public_bytes_raw()
        ).decode("ascii")

        trust = module.packaged_trust()
        self.assertFalse(trust.configured)
        self.assertIsNone(trust.channel)

        with patch.multiple(
            module,
            PACKAGED_SOURCE_URL="https://example.test",
            PACKAGED_KEY_ID="release-key",
            PACKAGED_PUBLIC_KEY_B64=public_b64,
            PACKAGED_CHANNEL="stable",
        ):
            trust = module.packaged_trust()
        self.assertTrue(trust.configured)
        self.assertEqual(trust.channel, "stable")
        self.assertEqual(trust.key_ids, ("release-key",))

        with patch.multiple(
            module,
            PACKAGED_SOURCE_URL="https://example.test",
            PACKAGED_KEY_ID="release-key",
            PACKAGED_PUBLIC_KEY_B64=public_b64,
            PACKAGED_CHANNEL="nightly",
        ):
            trust = module.packaged_trust()
        self.assertFalse(trust.configured)

        with patch.multiple(
            module,
            PACKAGED_SOURCE_URL="https://example.test",
            PACKAGED_KEY_ID="release-key",
            PACKAGED_PUBLIC_KEY_B64=public_b64,
            PACKAGED_CHANNEL="",
        ):
            trust = module.packaged_trust()
        self.assertTrue(trust.configured)
        self.assertIsNone(trust.channel)


if __name__ == "__main__":
    unittest.main()
