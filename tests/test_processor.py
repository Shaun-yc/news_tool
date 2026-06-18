import unittest
from unittest.mock import ANY, patch

from services.config import Settings
from services.processor import process_news


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


class ProcessorTests(unittest.TestCase):
    @patch("services.processor.classify_news")
    @patch("services.processor.scrape_article")
    def test_process_news_reports_fallback_counts(self, scrape_article, classify_news):
        scrape_article.return_value = {
            "en_title": "Fetch Failed (請手動確認)",
            "pubdate": "2026-06-01",
            "en_content": "無法自動爬取原文",
            "scrape_succeeded": False,
        }
        classify_news.return_value = ("排放管理;國際事務", False)
        settings = Settings(
            vllm_base_url="http://192.168.0.92:8000",
            vllm_model="test-model",
            vllm_temperature=0,
            vllm_max_tokens=256,
            scrape_delay_seconds=0,
            classify_delay_seconds=0,
            request_timeout_seconds=7,
            vllm_timeout_seconds=300,
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
        self.assertEqual(news_list[0]["subcategory"], "排放管理;國際事務")
        scrape_article.assert_called_once_with(
            ANY,
            "https://www.example.com/news/1",
            7,
        )
        classify_news.assert_called_once_with(
            "測試標題",
            "測試摘要",
            "http://192.168.0.92:8000",
            "test-model",
            300,
            0,
            256,
        )


if __name__ == "__main__":
    unittest.main()
