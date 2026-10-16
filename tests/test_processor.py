import unittest
from unittest.mock import ANY, patch

import requests

from services import classifier as classifier_service
from services.config import Settings
from services.processor import process_news


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


class ProcessorTests(unittest.TestCase):
    @patch("services.processor.wait_for_vllm", return_value=True)
    @patch("services.processor.align_summary_to_tags")
    @patch("services.processor.classify_news")
    @patch("services.processor.scrape_article")
    def test_process_news_reports_fallback_counts(
        self, scrape_article, classify_news, align_summary_to_tags, wait_for_vllm
    ):
        scrape_article.return_value = {
            "en_title": "Fetch Failed (請手動確認)",
            "pubdate": "2026-06-01",
            "en_content": "無法自動爬取原文",
            "scrape_succeeded": False,
        }
        classify_news.return_value = ("待人工確認", False)
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=0,
            request_timeout_seconds=7,
            vllm_timeout_seconds=300,
            classify_base_url="http://192.168.0.92:8001",
            classify_model="classify-model",
            classify_max_tokens=64,
            summary_align_max_tokens=384,
        )
        news_list = [
            {
                "zh_title": "測試標題",
                "content": "測試摘要",
                "source_url": "https://www.example.com/news/1",
            }
        ]

        summary = process_news(
            news_list,
            settings,
            session_factory=FakeSession,
            sleep=lambda seconds: None,
        )

        self.assertEqual(summary.total_count, 1)
        self.assertEqual(summary.scrape_failed_count, 1)
        self.assertEqual(summary.classification_fallback_count, 1)
        self.assertEqual(summary.summary_aligned_count, 0)
        self.assertEqual(news_list[0]["subcategory"], "待人工確認")
        scrape_article.assert_called_once_with(
            ANY,
            "https://www.example.com/news/1",
            7,
        )
        classify_news.assert_called_once_with(
            "測試標題",
            "測試摘要",
            "http://192.168.0.92:8001",
            "classify-model",
            300,
            0,
            64,
            english_content="",
        )
        align_summary_to_tags.assert_not_called()
        wait_for_vllm.assert_called_once_with(
            "http://192.168.0.92:8001",
            7,
            300,
            0,
            sleep=ANY,
        )

    @patch("services.processor.wait_for_vllm", return_value=True)
    @patch("services.processor.align_summary_to_tags")
    @patch("services.processor.classify_news")
    @patch("services.processor.scrape_article")
    def test_process_news_keeps_tags_and_updates_source_backed_summary(
        self, scrape_article, classify_news, align_summary_to_tags, wait_for_vllm
    ):
        scrape_article.return_value = {
            "en_title": "Source title",
            "pubdate": "2026-06-01",
            "en_content": "Source article evidence " * 20,
            "scrape_succeeded": True,
        }
        classify_news.return_value = ("碳定價;氣候法制", True)
        align_summary_to_tags.return_value = ("經對齊的中文摘要，保留來源支持的碳定價與法制事實。" * 4, True)
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=0,
            request_timeout_seconds=7,
            vllm_timeout_seconds=300,
            classify_base_url="http://192.168.0.92:8001",
            classify_model="classify-model",
            classify_max_tokens=64,
            summary_align_max_tokens=384,
            summary_align_enabled=True,
        )
        news_list = [{"zh_title": "測試標題", "content": "原摘要", "source_url": "https://example.com"}]

        summary = process_news(news_list, settings, session_factory=FakeSession, sleep=lambda _: None)

        self.assertEqual(news_list[0]["subcategory"], "碳定價;氣候法制")
        self.assertEqual(summary.summary_aligned_count, 1)
        align_summary_to_tags.assert_called_once()
        wait_for_vllm.assert_called_once()

    @patch("services.processor.wait_for_vllm", return_value=True)
    @patch("services.processor.align_summary_to_tags")
    @patch("services.processor.classify_news")
    @patch("services.processor.scrape_article")
    def test_process_news_keeps_original_summary_when_alignment_disabled(
        self, scrape_article, classify_news, align_summary_to_tags, wait_for_vllm
    ):
        scrape_article.return_value = {
            "en_title": "Source title",
            "pubdate": "2026-06-01",
            "en_content": "Source article evidence " * 20,
            "scrape_succeeded": True,
        }
        classify_news.return_value = ("碳定價;氣候法制", True)
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=0,
            request_timeout_seconds=7,
            vllm_timeout_seconds=300,
            classify_base_url="http://192.168.0.92:8001",
            classify_model="classify-model",
            classify_max_tokens=64,
            summary_align_max_tokens=384,
        )
        news_list = [{"zh_title": "測試標題", "content": "原摘要", "source_url": "https://example.com"}]

        summary = process_news(news_list, settings, session_factory=FakeSession, sleep=lambda _: None)

        self.assertEqual(news_list[0]["content"], "原摘要")
        self.assertEqual(summary.summary_aligned_count, 0)
        align_summary_to_tags.assert_not_called()
        wait_for_vllm.assert_called_once()

    @patch("services.processor.wait_for_vllm", return_value=False)
    @patch("services.processor.align_summary_to_tags")
    @patch("services.processor.classify_news")
    @patch("services.processor.scrape_article")
    def test_process_news_skips_remaining_items_after_classifier_timeout(
        self, scrape_article, classify_news, align_summary_to_tags, wait_for_vllm
    ):
        scrape_article.return_value = {
            "en_title": "Source title",
            "pubdate": "2026-06-01",
            "en_content": "Source article evidence " * 20,
            "scrape_succeeded": True,
        }
        classify_news.return_value = ("碳定價", True)
        align_summary_to_tags.return_value = ("原摘要", False)
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=2,
            request_timeout_seconds=7,
            vllm_timeout_seconds=300,
            classify_base_url="http://192.168.0.92:8001",
            classify_model="classify-model",
            classify_max_tokens=64,
            summary_align_max_tokens=384,
        )
        news_list = [
            {"zh_title": "第一則", "content": "摘要一", "source_url": "https://example.com/1"},
            {"zh_title": "第二則", "content": "摘要二", "source_url": "https://example.com/2"},
        ]

        summary = process_news(
            news_list, settings, session_factory=FakeSession, sleep=lambda _: None
        )

        classify_news.assert_not_called()
        wait_for_vllm.assert_called_once_with(
            "http://192.168.0.92:8001",
            7,
            300,
            2,
            sleep=ANY,
        )
        self.assertEqual(summary.classification_fallback_count, 2)
        self.assertEqual(news_list[0]["subcategory"], "待人工確認")
        self.assertEqual(news_list[1]["subcategory"], "待人工確認")

    @patch("services.classifier.requests.get")
    @patch("services.processor.align_summary_to_tags")
    @patch("services.processor.classify_news")
    @patch("services.processor.scrape_article")
    def test_process_news_classifies_after_health_recovers(
        self, scrape_article, classify_news, align_summary_to_tags, health
    ):
        scrape_article.return_value = {
            "en_title": "Source title",
            "pubdate": "2026-06-01",
            "en_content": "Source article evidence " * 20,
            "scrape_succeeded": True,
        }
        classify_news.return_value = ("碳定價", True)
        align_summary_to_tags.return_value = ("原摘要", False)
        healthy_response = requests.Response()
        healthy_response.status_code = 200
        health.side_effect = [
            requests.ConnectionError("connection refused"),
            healthy_response,
        ]
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=0,
            request_timeout_seconds=7,
            vllm_timeout_seconds=300,
            classify_base_url="http://192.168.0.92:8001",
            classify_model="classify-model",
            classify_max_tokens=64,
            summary_align_max_tokens=384,
        )
        news_list = [
            {"zh_title": "測試標題", "content": "原摘要", "source_url": "https://example.com"}
        ]

        summary = process_news(news_list, settings, session_factory=FakeSession, sleep=lambda _: None)

        self.assertEqual(summary.classification_fallback_count, 0)
        classify_news.assert_called_once()
        self.assertEqual(health.call_count, 2)

    def test_process_news_checks_health_once_and_preserves_classification_cooldown(self):
        scrape_result = {
            "en_title": "Source title",
            "pubdate": "2026-06-01",
            "en_content": "Source article evidence " * 20,
            "scrape_succeeded": True,
        }
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=0,
            request_timeout_seconds=7,
            vllm_timeout_seconds=30,
            classify_base_url="http://classify.local",
            classify_model="classify-model",
            classify_max_tokens=64,
            summary_align_max_tokens=384,
        )
        news_list = [
            {"zh_title": "第一則", "content": "摘要一", "source_url": "https://example.com/1"},
            {"zh_title": "第二則", "content": "摘要二", "source_url": "https://example.com/2"},
        ]
        health_response = requests.Response()
        health_response.status_code = 200
        failed_response = requests.Response()
        failed_response.status_code = 503

        classifier_service._vllm_unavailable_until.clear()
        try:
            with (
                patch("services.processor.scrape_article", return_value=scrape_result),
                patch("services.classifier.requests.get", return_value=health_response) as health,
                patch("services.classifier.requests.post", return_value=failed_response) as post,
            ):
                summary = process_news(
                    news_list,
                    settings,
                    session_factory=FakeSession,
                    sleep=lambda _: None,
                )
        finally:
            classifier_service._vllm_unavailable_until.clear()

        self.assertEqual(summary.classification_fallback_count, 2)
        self.assertEqual(news_list[0]["subcategory"], "待人工確認")
        self.assertEqual(news_list[1]["subcategory"], "待人工確認")
        self.assertEqual(health.call_count, 1)
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
