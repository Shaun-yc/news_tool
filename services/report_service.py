from __future__ import annotations

from datetime import datetime
import io
import re

from services.excel_exporter import build_excel_report
from services.config import Settings
from services.news_types import NewsItem
from services.processor import ProcessingSummary, process_news
from services.word_parser import parse_word_news


def get_week_date(filename: str) -> str:
    date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", filename)
    return "".join(date_match.groups()) if date_match else datetime.now().strftime("%Y%m%d")


def build_report_from_news_list(
    news_list: list[NewsItem], filename: str, settings: Settings, **process_kwargs
) -> tuple[io.BytesIO, str, ProcessingSummary]:
    if not news_list:
        raise ValueError("無法辨識新聞資料。請確認 Word 檔案包含標題總表、摘要與來源網址。")

    summary = process_news(news_list, settings, **process_kwargs)
    week_date = get_week_date(filename)
    output_filename = f"永智週新聞csv_{week_date}.xlsx"
    report = build_excel_report(news_list, week_date)
    return report, output_filename, summary


def build_weekly_news_report(
    file_object: object, filename: str, settings: Settings, **process_kwargs
) -> tuple[io.BytesIO, str, ProcessingSummary]:
    news_list = parse_word_news(file_object)
    return build_report_from_news_list(news_list, filename, settings, **process_kwargs)
