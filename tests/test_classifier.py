import unittest
from unittest.mock import patch

from services.classifier import REVIEW_REQUIRED, _classify_with_vllm, classify_news, normalize_tags


class ClassifierTests(unittest.TestCase):
    def test_normalize_tags_accepts_allowed_unique_tags(self):
        self.assertEqual(
            normalize_tags("碳定價; 氣候法制;碳定價"),
            "碳定價;氣候法制",
        )

    def test_normalize_tags_accepts_single_allowed_tag(self):
        self.assertEqual(normalize_tags("淨零科技"), "淨零科技")

    def test_normalize_tags_drops_unknown_tags(self):
        self.assertEqual(
            normalize_tags("未知標籤;碳足跡"),
            "碳足跡",
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
