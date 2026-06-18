import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from api import process_weekly_news
from services.processor import ProcessingSummary


class ApiTests(unittest.TestCase):
    @patch("api.build_weekly_news_report")
    def test_process_returns_excel_file(self, build_weekly_news_report):
        build_weekly_news_report.return_value = (
            io.BytesIO(b"excel-bytes"),
            "永智週新聞csv_20260618.xlsx",
            ProcessingSummary(
                total_count=2,
                scrape_failed_count=1,
                classification_fallback_count=0,
            ),
        )
        upload = UploadFile(
            filename="週新聞_2026.06.18.docx",
            file=io.BytesIO(b"docx-bytes"),
        )

        response = process_weekly_news(upload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.media_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(response.headers["x-news-total-count"], "2")
        self.assertEqual(response.headers["x-news-scrape-failed-count"], "1")
        self.assertEqual(response.headers["x-news-classification-fallback-count"], "0")

    def test_process_rejects_non_docx_file(self):
        upload = UploadFile(filename="news.txt", file=io.BytesIO(b"text"))

        with self.assertRaises(HTTPException) as error:
            process_weekly_news(upload)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "請上傳 .docx 週新聞檔案")


if __name__ == "__main__":
    unittest.main()
