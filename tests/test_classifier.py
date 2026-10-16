import unittest
from unittest.mock import patch

import requests

from services.classifier import (
    MAX_ENGLISH_EVIDENCE_CHARS,
    REVIEW_REQUIRED,
    SUMMARY_ALIGNMENT_KEEP_ORIGINAL,
    VLLM_UNAVAILABLE_COOLDOWN_SECONDS,
    _build_prompt,
    _build_summary_alignment_prompt,
    _classify_with_vllm,
    _select_english_evidence,
    _vllm_unavailable_until,
    align_summary_to_tags,
    classify_news,
    normalize_tags,
    wait_for_vllm,
)


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        _vllm_unavailable_until.clear()

    def tearDown(self):
        _vllm_unavailable_until.clear()

    def test_normalize_tags_accepts_allowed_unique_tags(self):
        self.assertEqual(
            normalize_tags("碳定價; 氣候法制;碳定價"),
            "碳定價;氣候法制",
        )

    def test_normalize_tags_accepts_single_allowed_tag(self):
        self.assertEqual(normalize_tags("淨零科技"), "淨零科技")

    def test_normalize_tags_drops_unknown_tags(self):
        self.assertEqual(
            normalize_tags("未知標籤;碳足跡;氣候法制"),
            "碳足跡;氣候法制",
        )

    def test_normalize_tags_rejects_none(self):
        self.assertIsNone(normalize_tags("NONE"))

    def test_normalize_tags_rejects_only_unknown_tags(self):
        self.assertIsNone(normalize_tags("未知標籤;其他說明"))

    def test_normalize_tags_limits_result_to_three(self):
        self.assertEqual(
            normalize_tags(
                "溫室氣體減量;氣候變遷調適;公約會議及進展;"
                "各國減碳目標(NDC);碳定價;氣候法制"
            ),
            "溫室氣體減量;氣候變遷調適;公約會議及進展",
        )

    def test_build_prompt_includes_chinese_summary_and_english_evidence(self):
        prompt = _build_prompt("中文標題", "中文摘要", "English source evidence")

        self.assertIn("中文標題：中文標題", prompt)
        self.assertIn("中文摘要：中文摘要", prompt)
        self.assertIn("英文原文證據：English source evidence", prompt)
        self.assertIn("選出 1～3 個最相關標籤", prompt)
        self.assertIn("單一核心主題時只選 1 個", prompt)

    def test_summary_alignment_prompt_locks_existing_tags(self):
        prompt = _build_summary_alignment_prompt(
            "中文標題",
            "中文摘要",
            "碳定價;氣候法制",
            "English source evidence",
        )

        self.assertIn("固定分類標籤", prompt)
        self.assertIn("碳定價;氣候法制", prompt)
        self.assertIn(SUMMARY_ALIGNMENT_KEEP_ORIGINAL, prompt)

    @patch("services.classifier.requests.post")
    def test_align_summary_keeps_original_when_evidence_is_insufficient(self, post):
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": SUMMARY_ALIGNMENT_KEEP_ORIGINAL}}]
        }

        summary, aligned = align_summary_to_tags(
            "標題",
            "原始摘要內容。",
            "碳定價;氣候法制",
            "http://localhost:8000",
            "test-model",
            300,
            0,
            384,
            "English source evidence",
        )

        self.assertEqual(summary, "原始摘要內容。")
        self.assertFalse(aligned)

    @patch("services.classifier.requests.post")
    def test_align_summary_skips_known_unavailable_service(self, post):
        base_url = "http://192.168.0.92:8000"
        _vllm_unavailable_until[base_url] = float("inf")

        with self.assertLogs("services.classifier", level="WARNING") as logs:
            summary, aligned = align_summary_to_tags(
                "標題",
                "原始摘要內容。",
                "碳定價;氣候法制",
                base_url,
                "test-model",
                300,
                0,
                384,
            )

        self.assertEqual(summary, "原始摘要內容。")
        self.assertFalse(aligned)
        post.assert_not_called()
        self.assertIn("Skipping summary alignment", logs.output[0])

    @patch("services.classifier.requests.post")
    def test_align_summary_preserves_tags_outside_summary_output(self, post):
        aligned_text = (
            "政府公布碳定價制度修法，明定執行規則與監督機制，以提升制度的可預測性與法規明確性。"
            * 3
        )
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": aligned_text}}]
        }

        summary, aligned = align_summary_to_tags(
            "標題",
            "原始摘要內容。",
            "碳定價;氣候法制",
            "http://localhost:8000",
            "test-model",
            300,
            0,
            384,
        )

        self.assertEqual(summary, aligned_text)
        self.assertTrue(aligned)

    def test_select_english_evidence_limits_prompt_input(self):
        evidence = _select_english_evidence("A" * 10000)

        self.assertIn("[中段省略]", evidence)
        self.assertLessEqual(
            len(evidence.replace("\n[中段省略]\n", "")),
            MAX_ENGLISH_EVIDENCE_CHARS,
        )

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_uses_valid_vllm_result(self, vllm):
        vllm.return_value = "碳定價;氣候法制"

        tags, succeeded = classify_news(
            "標題",
            "摘要",
            "http://192.168.0.92:8000",
            "diffusiongemma-4-26b",
            300,
            0,
            256,
        )

        self.assertEqual(tags, "碳定價;氣候法制")
        self.assertTrue(succeeded)

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_requires_review_when_model_returns_none(self, vllm):
        vllm.return_value = "NONE"

        with self.assertLogs("services.classifier", level="WARNING"):
            tags, succeeded = classify_news(
                "標題",
                "摘要",
                "http://192.168.0.92:8000",
                "diffusiongemma-4-26b",
                300,
                0,
                256,
            )

        self.assertEqual(tags, REVIEW_REQUIRED)
        self.assertFalse(succeeded)

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_accepts_one_valid_tag(self, vllm):
        vllm.return_value = "淨零科技"

        tags, succeeded = classify_news(
            "標題",
            "摘要",
            "http://192.168.0.92:8000",
            "diffusiongemma-4-26b",
            300,
            0,
            256,
        )

        self.assertEqual(tags, "淨零科技")
        self.assertTrue(succeeded)

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_requires_review_when_vllm_fails(self, vllm):
        vllm.side_effect = RuntimeError("vllm failed")

        with self.assertLogs("services.classifier", level="ERROR") as logs:
            tags, succeeded = classify_news(
                "標題",
                "摘要",
                "http://192.168.0.92:8000",
                "diffusiongemma-4-26b",
                300,
                0,
                256,
            )

        self.assertEqual(tags, REVIEW_REQUIRED)
        self.assertFalse(succeeded)
        self.assertIn("vLLM classification failed for title: 標題", logs.output[0])

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_continues_after_bad_request(self, vllm):
        response = requests.Response()
        response.status_code = 400
        vllm.side_effect = [
            requests.HTTPError("400 Client Error", response=response),
            "碳定價;氣候法制",
        ]

        with self.assertLogs("services.classifier", level="ERROR"):
            first_tags, first_succeeded = classify_news(
                "第一則",
                "摘要",
                "http://192.168.0.92:8001",
                "gemma-4-e4b",
                300,
                0,
                256,
            )
        second_tags, second_succeeded = classify_news(
            "第二則",
            "摘要",
            "http://192.168.0.92:8001",
            "gemma-4-e4b",
            300,
            0,
            256,
        )

        self.assertEqual(first_tags, REVIEW_REQUIRED)
        self.assertFalse(first_succeeded)
        self.assertEqual(second_tags, "碳定價;氣候法制")
        self.assertTrue(second_succeeded)
        self.assertEqual(vllm.call_count, 2)

    @patch("services.classifier.time.monotonic")
    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_opens_cooldown_when_vllm_service_is_unavailable(
        self, vllm, monotonic
    ):
        monotonic.return_value = 100
        vllm.side_effect = requests.ConnectionError("connection refused")

        with self.assertLogs("services.classifier", level="ERROR") as logs:
            tags, succeeded = classify_news(
                "標題",
                "摘要",
                "http://192.168.0.92:8001",
                "gemma-4-e4b",
                300,
                0,
                256,
            )

        self.assertEqual(tags, REVIEW_REQUIRED)
        self.assertFalse(succeeded)
        self.assertEqual(vllm.call_count, 1)
        self.assertIn("service unavailable", logs.output[0])

        with self.assertLogs("services.classifier", level="WARNING") as logs:
            tags, succeeded = classify_news(
                "第二篇",
                "摘要",
                "http://192.168.0.92:8001",
                "gemma-4-e4b",
                300,
                0,
                256,
            )

        self.assertEqual(tags, REVIEW_REQUIRED)
        self.assertFalse(succeeded)
        self.assertEqual(vllm.call_count, 1)
        self.assertIn("Skipping vLLM classification", logs.output[0])

    @patch("services.classifier.time.monotonic")
    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_retries_after_vllm_cooldown_expires(self, vllm, monotonic):
        monotonic.side_effect = [
            100,
            100,
            100 + VLLM_UNAVAILABLE_COOLDOWN_SECONDS + 1,
        ]
        vllm.side_effect = [
            requests.ConnectionError("connection refused"),
            "碳定價;氣候法制",
        ]

        classify_news(
            "標題",
            "摘要",
            "http://192.168.0.92:8001",
            "gemma-4-e4b",
            300,
            0,
            256,
        )
        tags, succeeded = classify_news(
            "冷卻後",
            "摘要",
            "http://192.168.0.92:8001",
            "gemma-4-e4b",
            300,
            0,
            256,
        )

        self.assertEqual(tags, "碳定價;氣候法制")
        self.assertTrue(succeeded)
        self.assertEqual(vllm.call_count, 2)

    @patch("services.classifier.requests.get")
    def test_wait_for_vllm_waits_for_recovery_and_clears_cooldown(self, health):
        base_url = "http://192.168.0.92:8001"
        _vllm_unavailable_until[base_url] = float("inf")
        healthy_response = requests.Response()
        healthy_response.status_code = 200
        clock = [100.0]

        def monotonic():
            return clock[0]

        def sleep(seconds):
            clock[0] += seconds

        health.side_effect = [
            requests.ConnectionError("connection refused"),
            healthy_response,
        ]

        self.assertTrue(
            wait_for_vllm(
                base_url,
                health_timeout=7,
                total_timeout=30,
                poll_interval=5,
                sleep=sleep,
                monotonic=monotonic,
            )
        )

        self.assertNotIn(base_url, _vllm_unavailable_until)
        self.assertEqual(health.call_count, 2)
        health.assert_any_call("http://192.168.0.92:8001/health", timeout=7)

    @patch("services.classifier.requests.get")
    def test_wait_for_vllm_returns_false_after_total_timeout(self, health):
        base_url = "http://192.168.0.92:8001"
        clock = [100.0]

        def monotonic():
            return clock[0]

        def sleep(seconds):
            clock[0] += seconds

        health.side_effect = requests.ConnectionError("connection refused")

        self.assertFalse(
            wait_for_vllm(
                base_url,
                health_timeout=7,
                total_timeout=5,
                poll_interval=2,
                sleep=sleep,
                monotonic=monotonic,
            )
        )

        self.assertIn(base_url, _vllm_unavailable_until)
        self.assertGreaterEqual(health.call_count, 1)

    @patch("services.classifier.requests.get")
    def test_wait_for_vllm_bounds_request_by_remaining_budget(self, health):
        clock = [100.0]

        def timed_out_health(url, timeout):
            clock[0] += timeout
            raise requests.Timeout("health request timed out")

        health.side_effect = timed_out_health

        ready = wait_for_vllm(
            "http://classify.local",
            health_timeout=7,
            total_timeout=2,
            poll_interval=1,
            sleep=lambda seconds: self.fail("deadline exhausted; must not sleep"),
            monotonic=lambda: clock[0],
        )

        self.assertFalse(ready)
        health.assert_called_once_with("http://classify.local/health", timeout=2)
        self.assertEqual(clock[0], 102.0)

    @patch("services.classifier.requests.post")
    def test_vllm_request_uses_chat_completions(self, post):
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "碳定價;氣候法制"}}]
        }

        with self.assertLogs("services.classifier", level="INFO") as logs:
            result = _classify_with_vllm(
                "http://192.168.0.92:8000",
                "diffusiongemma-4-26b",
                "prompt",
                300,
                0.2,
                128,
            )

        self.assertEqual(result, "碳定價;氣候法制")
        self.assertIn("classification request started", logs.output[0])
        post.assert_called_once_with(
            "http://192.168.0.92:8000/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": "diffusiongemma-4-26b",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是嚴格的標籤分類器。只能從用戶指定的標籤池中選取標籤，"
                            "以分號分隔輸出；若沒有充分依據則輸出 NONE。"
                            "絕對不輸出其他文字、解釋或說明。"
                        ),
                    },
                    {"role": "user", "content": "prompt"},
                ],
                "temperature": 0.2,
                "max_tokens": 128,
                "stop": ["\n\n", "（", "解釋", "說明：", "Note:"],
            },
            timeout=300,
        )
        post.return_value.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
