from dataclasses import dataclass
import time

import requests

from services.classifier import classify_news
from services.config import Settings
from services.scraper import scrape_article


@dataclass(frozen=True)
class ProcessingSummary:
    total_count: int
    scrape_failed_count: int
    classification_fallback_count: int


def process_news(
    news_list,
    settings: Settings,
    on_scrape_progress=lambda current, total, news: None,
    on_classify_progress=lambda current, total, news: None,
    session_factory=requests.Session,
    sleep=time.sleep,
):
    """Enrich parsed news items with source content and AI classifications."""
    total_count = len(news_list)
    scrape_failed_count = 0
    classification_fallback_count = 0

    with session_factory() as session:
        for index, news in enumerate(news_list, start=1):
            on_scrape_progress(index, total_count, news)
            scraped = scrape_article(session, news["source_url"], settings.request_timeout_seconds)
            news.update(scraped)
            if not scraped["scrape_succeeded"]:
                scrape_failed_count += 1
            if index < total_count:
                sleep(settings.scrape_delay_seconds)

    for index, news in enumerate(news_list, start=1):
        on_classify_progress(index, total_count, news)
        tags, succeeded = classify_news(
            news["zh_title"],
            news["content"],
            settings.vllm_base_url,
            settings.vllm_model,
            settings.vllm_timeout_seconds,
            settings.vllm_temperature,
            settings.vllm_max_tokens,
        )
        news["subcategory"] = tags
        news["classification_succeeded"] = succeeded
        if not succeeded:
            classification_fallback_count += 1
        if index < total_count:
            sleep(settings.classify_delay_seconds)

    return ProcessingSummary(
        total_count=total_count,
        scrape_failed_count=scrape_failed_count,
        classification_fallback_count=classification_fallback_count,
    )
