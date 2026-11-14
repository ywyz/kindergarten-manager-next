"""Curriculum split strict JSON over the real SSE parser (synthetic frames).

The report saw provider thinking end in "Final answer" while the structured
split failed.  This test uses the production stream parser with a synthetic
DeepSeek-shaped SSE body: reasoning text (including a fake final answer) must
stay display-only, and only one complete content JSON object may become the
candidate.  No network or real provider is involved.
"""

from __future__ import annotations

import json
import unittest

from app.local import ai_transport
from tests.local.test_d2_streaming import _FakeSock, _event, _http


def _send(body: bytes) -> ai_transport.TransportResult:
    prepared = ai_transport.Prepared(
        sock=_FakeSock(_http(body, content_type="text/event-stream")),
        host="api.example.com",
        netloc="api.example.com",
        path="/chat/completions",
        request_bytes=b"",
    )
    return ai_transport.send(
        prepared,
        deadline_ms=ai_transport.now_ticks() + 60_000,
        budget=ai_transport.CURRICULUM_TEXT_RESPONSE_BUDGET,
    )


class CurriculumStreamContractTests(unittest.TestCase):
    def _candidate(self) -> dict:
        return {
            "blocks": [
                {
                    "source_id": "s1",
                    "quote": "一、活动目标",
                    "section": "goals",
                    "kind": "heading",
                    "text": "一、活动目标",
                }
            ],
            "questions": [],
        }

    def test_reasoning_final_answer_is_display_only(self):
        content = json.dumps(self._candidate(), ensure_ascii=False)
        body = (
            _event(
                {
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "整理原稿。\nFinal answer:\n"
                                + content
                            }
                        }
                    ]
                }
            )
            + _event(
                {
                    "choices": [
                        {
                            "delta": {"content": content},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
            + _event("[DONE]")
        )
        result = _send(body)
        self.assertEqual(result.kind, ai_transport.SUCCESS, result)
        self.assertEqual(result.candidate_text, content)
        parsed = ai_transport.parse_strict_json_object(result.candidate_text)
        self.assertEqual(parsed, self._candidate())
        # The stream has one data-bearing request/response only; the test helper
        # would fail if a retry were attempted at this layer.
        self.assertEqual(result.sent, True)

    def test_reasoning_only_is_rejected_not_used_as_split(self):
        content = json.dumps(self._candidate(), ensure_ascii=False)
        body = _event(
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "Final answer:\n" + content
                        }
                    }
                ]
            }
        ) + _event("[DONE]")
        result = _send(body)
        self.assertEqual(result.kind, ai_transport.OUTPUT_INVALID)
        self.assertEqual(result.detail, ai_transport.DETAIL["reasoning_only"])
        self.assertIsNone(result.candidate_text)

    def test_extra_output_field_is_not_silently_accepted(self):
        bad = self._candidate()
        bad["extra"] = "not allowed"
        content = json.dumps(bad, ensure_ascii=False)
        body = (
            _event(
                {
                    "choices": [
                        {
                            "delta": {"content": content},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
            + _event("[DONE]")
        )
        result = _send(body)
        # Transport only proves the content is one JSON object; the curriculum
        # contract gate rejects the extra field.  Both layers are strict and
        # there is no automatic repair/retry.
        self.assertEqual(result.kind, ai_transport.SUCCESS)
        parsed = ai_transport.parse_strict_json_object(result.candidate_text)
        self.assertIn("extra", parsed)
        from app.local import curriculum_ai, curriculum_ai_contracts

        with self.assertRaises(curriculum_ai.CandidateInvalid):
            curriculum_ai.validate_candidate_for_input(
                curriculum_ai_contracts.TASK_SPLIT,
                parsed,
                type(
                    "InputRow",
                    (),
                    {
                        "payload_json": {
                            "source_blocks": [{"source_id": "s1", "text": "一、活动目标"}]
                        },
                        "dependencies_json": {},
                    },
                )(),
            )


if __name__ == "__main__":
    unittest.main()
