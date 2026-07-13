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

    def test_normalize_tags_rejects_single_allowed_tag(self):
        self.assertIsNone(normalize_tags("淨零科技"))

    def test_normalize_tags_drops_unknown_tags(self):
        self.assertEqual(
            normalize_tags("未知標籤;碳足跡;氣候法制"),
            "碳足跡;氣候法制",
        )

    def test_normalize_tags_rejects_none(self):
        self.assertIsNone(normalize_tags("NONE"))

    def test_normalize_tags_rejects_only_unknown_tags(self):
        self.assertIsNone(normalize_tags("未知標籤;其他說明"))

    def test_normalize_tags_limits_result_to_five(self):
        self.assertEqual(
            normalize_tags(
                "溫室氣體減量;氣候變遷調適;公約會議及進展;"
                "各國減碳目標(NDC);碳定價;氣候法制"
            ),
            "溫室氣體減量;氣候變遷調適;公約會議及進展;"
            "各國減碳目標(NDC);碳定價",
        )

    def test_build_prompt_includes_chinese_summary_and_english_evidence(self):
        prompt = _build_prompt("中文標題", "中文摘要", "English source evidence")

        self.assertIn("中文標題：中文標題", prompt)
        self.assertIn("中文摘要：中文摘要", prompt)
        self.assertIn("英文原文證據：English source evidence", prompt)

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
    def test_classify_news_requires_review_when_only_one_tag_is_valid(self, vllm):
        vllm.return_value = "淨零科技"

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

    @patch("services.classifier.requests.post")
    def test_vllm_request_uses_chat_completions(self, post):
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "碳定價;氣候法制"}}]
        }

        result = _classify_with_vllm(
            "http://192.168.0.92:8000",
            "diffusiongemma-4-26b",
            "prompt",
            300,
            0.2,
            128,
        )

        self.assertEqual(result, "碳定價;氣候法制")
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
