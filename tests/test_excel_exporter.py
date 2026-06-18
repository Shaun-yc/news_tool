import unittest

import openpyxl

from services.excel_exporter import build_excel_report, extract_source, format_date


class ExcelExporterTests(unittest.TestCase):
    def test_extract_source_uses_first_domain_segment(self):
        self.assertEqual(extract_source("https://www.example.com/news/1"), "EXAMPLE")
        self.assertEqual(extract_source(""), "LINK")

    def test_format_date_uses_report_format(self):
        self.assertEqual(format_date("2026-06-01"), "2026/06/01")
        self.assertEqual(format_date("unknown"), "unknown")

    def test_build_excel_report_keeps_standard_columns(self):
        report = build_excel_report(
            [
                {
                    "zh_title": "中文標題",
                    "en_title": "English title",
                    "subcategory": "排放管理;國際事務",
                    "pubdate": "2026-06-01",
                    "source_url": "https://www.example.com/news/1",
                    "content": "中文摘要",
                    "en_content": "English content",
                }
            ],
            "20260601",
        )
        workbook = openpyxl.load_workbook(report)
        worksheet = workbook["週新聞"]

        self.assertEqual(worksheet.max_column, 14)
        self.assertEqual(worksheet.max_row, 2)
        self.assertEqual(worksheet["A2"].value, "20260601_01")
        self.assertEqual(worksheet["B2"].value, "中文標題\nEnglish title")
        self.assertEqual(worksheet["H2"].value, "2026/06/01")
        self.assertEqual(worksheet["I2"].value, "EXAMPLE")


if __name__ == "__main__":
    unittest.main()

