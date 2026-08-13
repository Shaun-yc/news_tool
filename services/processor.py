from __future__ import annotations

import logging
from dataclasses import dataclass
import time
from typing import Any, Callable

import requests

from services.classifier import align_summary_to_tags, classify_news
from services.config import Settings
from services.news_types import NewsItem
from services.scraper import scrape_article

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ProcessingSummary:
    total_count: int
    scrape_failed_count: int
    classification_fallback_count: int
    summary_aligned_count: int = 0


def process_news(
    news_list: list[NewsItem],
    settings: Settings,
    on_scrape_progress: Callable[[int, int, NewsItem], None] =
        lambda current, total, news: None,
    on_classify_progress: Callable[[int, int, NewsItem], None] =
        lambda current, total, news: None,
    session_factory: Callable[..., Any] = requests.Session,
    sleep: Callable[[float], Any] = time.sleep,
) -> ProcessingSummary:
    """Enrich parsed news items with source content and AI classifications."""
    total_count = len(news_list)
    scrape_failed_count = 0
    classification_fallback_count = 0
    summary_aligned_count = 0

    logger.info("Weekly news processing started: total=%s", total_count)

    with session_factory() as session:
        for index, news in enumerate(news_list, start=1):
            on_scrape_progress(index, total_count, news)
            scraped = scrape_article(session, news["source_url"], settings.request_timeout_seconds)
            news.update(scraped)
            if not scraped["scrape_succeeded"]:
                scrape_failed_count += 1
            logger.info(
                "Scrape completed: index=%s/%s success=%s content_chars=%s url=%s",
                index,
                total_count,
                scraped["scrape_succeeded"],
                len(scraped.get("en_content", "")),
                news["source_url"],
            )
            if index < total_count:
                sleep(settings.scrape_delay_seconds)

    for index, news in enumerate(news_list, start=1):
        on_classify_progress(index, total_count, news)
        tags, succeeded = classify_news(
            news["zh_title"],
            news["content"],
            settings.classify_base_url,
            settings.classify_model,
            settings.vllm_timeout_seconds,
            settings.vllm_temperature,
            settings.classify_max_tokens,
            english_content=news.get("en_content", "") if news.get("scrape_succeeded") else "",
        )
        news["subcategory"] = tags
        news["classification_succeeded"] = succeeded
        if not succeeded:
            classification_fallback_count += 1
        else:
            aligned_content, aligned = align_summary_to_tags(
                news["zh_title"],
                news["content"],
                tags,
                settings.vllm_base_url,
                settings.vllm_model,
                settings.vllm_timeout_seconds,
                settings.vllm_temperature,
                settings.summary_align_max_tokens,
                english_content=news.get("en_content", "") if news.get("scrape_succeeded") else "",
            )
            news["content"] = aligned_content
            summary_aligned_count += int(aligned)
        logger.info(
            "Classification completed: index=%s/%s success=%s tag_count=%s",
            index,
            total_count,
            succeeded,
            len(tags.split(";")) if succeeded else 0,
        )
        if index < total_count:
            sleep(settings.classify_delay_seconds)

    summary = ProcessingSummary(
        total_count=total_count,
        scrape_failed_count=scrape_failed_count,
        classification_fallback_count=classification_fallback_count,
        summary_aligned_count=summary_aligned_count,
    )
    logger.info(
        "Weekly news processing completed: total=%s scrape_failed=%s "
        "classification_fallback=%s summary_aligned=%s",
        summary.total_count,
        summary.scrape_failed_count,
        summary.classification_fallback_count,
        summary.summary_aligned_count,
    )
    return summary
