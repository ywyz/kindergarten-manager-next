"""E06 vision header/capability/capacity contract tests."""

from __future__ import annotations

import json
import multiprocessing
import time
import uuid

from app.local import ai_transport, ai_worker, observation_ai_inputs
from tests.local.support import LocalTestCase


def _spawn_worker(frames, *, timeout=5.0):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=True)
    process = ctx.Process(target=ai_worker.worker_entry, args=(child,), daemon=False)
    process.start()
    child.close()
    try:
        for frame in frames:
            parent.send_bytes(frame)
    except Exception:  # noqa: BLE001 - worker may already have rejected
        pass
    result = None
    if parent.poll(timeout):
        try:
            result = json.loads(bytes(parent.recv_bytes(2 * 1024 * 1024)).decode("utf-8"))
        except Exception:  # noqa: BLE001
            result = None
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
    parent.close()
    return result, process.exitcode


class VisionHeaderTests(LocalTestCase):
    def _header(self, **overrides):
        value = {
            "type": "bootstrap_header",
            "vision": True,
            "protocol": ai_transport.VISION_PROTOCOL_ID,
            "schema_version": 1,
            "source_kind": "game_observation",
            "task_type": "game_observation_generate",
            "contract_version": 1,
            "image_count": 1,
            "frame_size": 100,
        }
        value.update(overrides)
        return value

    def test_header_only_contract(self):
        self.assertTrue(ai_worker.validate_vision_header(self._header()))
        for bad in (
            self._header(source_kind="daily_plan"),
            self._header(task_type="daily_lesson_split"),
            self._header(schema_version=2),
            self._header(contract_version=2),
            self._header(protocol="chat_completions_v1"),
            self._header(image_count=0),
            self._header(image_count=601),
            self._header(frame_size=0),
        ):
            with self.subTest(bad=bad):
                self.assertFalse(ai_worker.validate_vision_header(bad))

    def test_invalid_header_only_is_rejected_without_body(self):
        result, exitcode = _spawn_worker(
            [json.dumps(self._header(source_kind="daily_plan")).encode("utf-8")]
        )
        self.assertEqual(exitcode, 0)
        self.assertIsNotNone(result)
        self.assertEqual(result["result"]["kind"], "policy")
        self.assertEqual(result["result"]["detail"], "vision_not_authorized")

    def test_vision_bootstrap_without_header_is_rejected(self):
        frame = {
            "type": "bootstrap",
            "deadline_ms": 10_000,
            "request": {
                "protocol": ai_transport.VISION_PROTOCOL_ID,
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-flash",
                "system_text": "x",
                "user_text": "{}",
                "image_urls": ["data:image/jpeg;base64,AA=="],
            },
        }
        result, exitcode = _spawn_worker(
            [json.dumps(frame).encode("utf-8")]
        )
        self.assertEqual(exitcode, 0)
        self.assertIsNotNone(result)
        self.assertEqual(result["result"]["kind"], "policy")
        self.assertEqual(result["result"]["detail"], "vision_header_required")

    def test_fake_daily_header_then_body_is_rejected(self):
        header = self._header(
            source_kind="daily_plan",
            task_type="daily_lesson_split",
            frame_size=200,
        )
        body = {
            "type": "bootstrap",
            "deadline_ms": 10_000,
            "request": {
                "protocol": ai_transport.VISION_PROTOCOL_ID,
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-flash",
                "system_text": "x",
                "user_text": "{}",
                "image_urls": ["data:image/jpeg;base64,AA=="],
            },
        }
        result, exitcode = _spawn_worker(
            [
                json.dumps(header).encode("utf-8"),
                json.dumps(body).encode("utf-8"),
            ]
        )
        self.assertEqual(exitcode, 0)
        self.assertIsNotNone(result)
        self.assertEqual(result["result"]["kind"], "policy")


class VisionCapacityTests(LocalTestCase):
    def test_601_images_rejected_before_body_build(self):
        urls = [f"data:image/jpeg;base64,{'A' * 8}" for _ in range(601)]
        with self.assertRaises(Exception) as caught:
            observation_ai_inputs.preflight_vision_request(
                base_url="https://api.deepseek.com/v1",
                model="deepseek-flash",
                secret="x",
                system_text="s",
                user_text="{}",
                image_urls=urls,
            )
        self.assertEqual(getattr(caught.exception, "code", None), "AI_INPUT_TOO_LARGE")

    def test_preflight_frame_matches_shared_builder(self):
        urls = [f"data:image/jpeg;base64,{'A' * 8}" for _ in range(2)]
        result = observation_ai_inputs.preflight_vision_request(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-flash",
            secret="x" * 4096,
            system_text="s",
            user_text="{}",
            image_urls=urls,
        )
        frames = observation_ai_inputs.build_vision_frames(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-flash",
            secret="x" * 4096,
            system_text="s",
            user_text="{}",
            image_urls=urls,
            deadline_ms=9_999_999_999_999,
            task_type="game_observation_generate",
            contract_version=1,
        )
        self.assertEqual(result["frame_bytes"], sum(len(frame) for frame in frames))
        self.assertEqual(result["header_bytes"], len(frames[0]))
        self.assertEqual(json.loads(frames[0])["frame_size"], len(frames[1]))

    def test_capability_official_hosts_only(self):
        for base_url, model, expected in (
            ("https://api.deepseek.com", "deepseek-flash", True),
            ("https://api.deepseek.com/v1/", "deepseek-flash", True),
            ("https://api.xiaomimimo.com/v1", "mimo-v2.6-flash", True),
            ("https://api.xiaomimimo.com/v1", "mimo-v2.6-pro", True),
            ("https://api.xiaomimimo.com/v1", "mimo-v2.6-pro-ultraspeed", True),
            ("https://api.xiaomimimo.com/v1", "mimo-v2.5", False),
            ("https://api.xiaomimimo.com/token-plan/v1", "mimo-v2.6-flash", False),
            ("https://foo.xiaomimimo.com/v1", "mimo-v2.6-flash", False),
            ("https://api.deepseek.com/v1/chat", "deepseek-flash", False),
            ("https://api.deepseek.com:443/v1", "deepseek-flash", True),
        ):
            with self.subTest(base_url=base_url, model=model):
                self.assertEqual(
                    ai_transport.vision_capability(base_url, model), expected
                )

    def test_context_uses_work_dimensions_and_rejects_mimo_600_high_res(self):
        urls = [f"data:image/jpeg;base64,{'A' * 8}" for _ in range(600)]
        with self.assertRaises(Exception) as caught:
            observation_ai_inputs.check_vision_context(
                base_url="https://api.xiaomimimo.com/v1",
                model="mimo-v2.6-flash",
                system_text="s",
                user_text="{}",
                work_dimensions=[(2048, 2048)] * 600,
            )
        self.assertEqual(getattr(caught.exception, "code", None), "AI_INPUT_TOO_LARGE")
        # DeepSeek's per-image cap keeps the same count under 1M, while a large
        # actual text body can still cross the boundary.
        observation_ai_inputs.check_vision_context(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-flash",
            system_text="s",
            user_text="{}",
            work_dimensions=[(2048, 2048)] * 600,
        )
        with self.assertRaises(Exception):
            observation_ai_inputs.check_vision_context(
                base_url="https://api.deepseek.com/v1",
                model="deepseek-flash",
                system_text="s",
                user_text="x" * 400_000,
                work_dimensions=[(2048, 2048)] * 600,
            )
        self.assertEqual(observation_ai_inputs.mimo_image_tokens(2048, 2048), 4096)
        self.assertEqual(observation_ai_inputs.deepseek_image_tokens(2048, 2048), 1024)

    def test_preflight_rejects_mimo_context_before_building_body(self):
        urls = [f"data:image/jpeg;base64,{'A' * 8}" for _ in range(600)]
        with self.assertRaises(Exception) as caught:
            observation_ai_inputs.preflight_vision_request(
                base_url="https://api.xiaomimimo.com/v1",
                model="mimo-v2.6-flash",
                secret="x",
                system_text="s",
                user_text="{}",
                image_urls=urls,
                work_dimensions=[(2048, 2048)] * 600,
            )
        self.assertEqual(getattr(caught.exception, "code", None), "AI_INPUT_TOO_LARGE")
        observation_ai_inputs.preflight_vision_request(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-flash",
            secret="x",
            system_text="s",
            user_text="{}",
            image_urls=urls,
            work_dimensions=[(2048, 2048)] * 600,
        )

    def test_old_text_frame_above_one_mib_is_not_received(self):
        import threading

        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=True)
        process = ctx.Process(target=ai_worker.worker_entry, args=(child,), daemon=False)
        process.start()
        child.close()
        payload = b'{"type":"bootstrap","request":{"user_text":"' + (
            b"a" * (ai_transport.REQUEST_MAX_BYTES + 1024)
        ) + b'"}}'

        def send() -> None:
            try:
                parent.send_bytes(payload)
            except Exception:  # noqa: BLE001
                pass

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        process.join(5)
        alive = process.is_alive()
        if alive:
            process.terminate()
            process.join(5)
        parent.close()
        self.assertFalse(alive)
        self.assertEqual(process.exitcode, 0)

    def test_parent_bootstrap_rejects_forged_daily_vision_and_matches_preflight(self):
        from app.local import ai_executor, ai_task_service

        def claim(**overrides):
            values = dict(
                task_id="t",
                plan_id=None,
                input_id="i",
                task_type="game_observation_generate",
                execution_id="e",
                generation=1,
                attempt_id="a",
                attempt_no=1,
                permit_id="p",
                launch_id="l",
                config_version=1,
                personal_revision=1,
                contract_version=1,
                default_revision=1,
                payload={"photos": []},
                system_text="s",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-flash",
                secret="x",
                source_kind="game_observation",
                observation_id="o",
                image_urls=("data:image/jpeg;base64,AA==",),
                vision_authorized=True,
                vision_schema_version=1,
                vision_protocol=ai_transport.VISION_PROTOCOL_ID,
                work_dimensions=((2048, 2048),),
            )
            values.update(overrides)
            return ai_task_service.Claim(**values)

        with self.assertRaises(ValueError):
            ai_executor._encode_bootstrap(
                claim(source_kind="daily_plan", task_type="daily_lesson_split"),
                9_999_999_999_999,
            )
        with self.assertRaises(ValueError):
            ai_executor._encode_bootstrap(
                claim(vision_schema_version=2), 9_999_999_999_999
            )
        with self.assertRaises(ValueError):
            ai_executor._encode_bootstrap(
                claim(work_dimensions=()), 9_999_999_999_999
            )
        frames = ai_executor._encode_bootstrap(
            claim(), 9_999_999_999_999
        )
        preflight = observation_ai_inputs.preflight_vision_request(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-flash",
            secret="x",
            system_text="s",
            user_text=json.dumps({"photos": []}, separators=(",", ":")),
            image_urls=["data:image/jpeg;base64,AA=="],
            work_dimensions=[(2048, 2048)],
        )
        self.assertEqual(sum(len(frame) for frame in frames), preflight["frame_bytes"])

    def test_http_write_uses_remaining_attempt_budget_not_connect_timeout(self):
        import socket as _socket

        class _SlowSock:
            def __init__(self):
                self.timeout = None
                self.closed = False

            def settimeout(self, value):
                self.timeout = value

            def sendall(self, _data):
                raise _socket.timeout("slow upload")

            def close(self):
                self.closed = True

        for budget, minimum in ((180_000, 170.0), (120_000, 110.0)):
            sock = _SlowSock()
            prepared = ai_transport.Prepared(
                sock=sock,
                host="api.deepseek.com",
                netloc="api.deepseek.com",
                path="/v1/chat/completions",
                request_bytes=b"x",
            )
            result = ai_transport.send(
                prepared,
                deadline_ms=ai_transport.now_ticks() + budget,
            )
            self.assertEqual(result.kind, ai_transport.UNKNOWN)
            self.assertIsNotNone(sock.timeout)
            self.assertGreaterEqual(sock.timeout, minimum)
