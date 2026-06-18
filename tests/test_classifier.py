import unittest
from unittest.mock import patch

from services.classifier import DEFAULT_TAGS, _classify_with_vllm, classify_news, normalize_tags


class ClassifierTests(unittest.TestCase):
    def test_normalize_tags_accepts_allowed_unique_tags(self):
        self.assertEqual(
            normalize_tags("排放管理; 減量交易;氣候法規"),
            "排放管理;減量交易;氣候法規",
        )

    def test_normalize_tags_drops_unknown_tags_and_adds_fallback(self):
        self.assertEqual(normalize_tags("排放管理;未知標籤"), "排放管理;國際事務")

    def test_normalize_tags_deduplicates_and_adds_fallback(self):
        self.assertEqual(normalize_tags("排放管理;排放管理"), "排放管理;國際事務")

    def test_normalize_tags_drops_unknown_tags_and_keeps_allowed_tags(self):
        self.assertEqual(
            normalize_tags("政策監管;排放管理;氣候法規"),
            "排放管理;氣候法規",
        )

    def test_normalize_tags_adds_fallback_when_only_one_allowed_tag_remains(self):
        self.assertEqual(
            normalize_tags("政策監管;氣候法規"),
            "氣候法規;排放管理",
        )

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_uses_vllm(self, vllm):
        vllm.return_value = "排放管理;國際事務"

        tags, succeeded = classify_news(
            "標題",
            "摘要",
            "http://192.168.0.92:8000",
            "diffusiongemma-4-26b",
            300,
            0,
            256,
        )

        self.assertEqual(tags, "排放管理;國際事務")
        self.assertTrue(succeeded)

    @patch("services.classifier._classify_with_vllm")
    def test_classify_news_uses_default_when_vllm_fails(self, vllm):
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

        self.assertEqual(tags, DEFAULT_TAGS)
        self.assertFalse(succeeded)
        self.assertIn("vLLM classification failed for title: 標題", logs.output[0])

    @patch("services.classifier.requests.post")
    def test_vllm_request_uses_chat_completions(self, post):
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "排放管理;國際事務"}}]
        }

        result = _classify_with_vllm(
            "http://192.168.0.92:8000",
            "diffusiongemma-4-26b",
            "prompt",
            300,
            0.2,
            128,
        )

        self.assertEqual(result, "排放管理;國際事務")
        post.assert_called_once_with(
            "http://192.168.0.92:8000/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": "diffusiongemma-4-26b",
                "messages": [{"role": "user", "content": "prompt"}],
                "temperature": 0.2,
                "max_tokens": 128,
            },
            timeout=300,
        )
        post.return_value.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
