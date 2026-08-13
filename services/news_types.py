"""Static contracts shared by the news processing pipeline.

The pipeline intentionally keeps passing ordinary mutable dictionaries between
stages.  These ``TypedDict`` definitions document the keys each stage reads or
adds without introducing runtime validation or normalization.
"""

from typing import NotRequired, TypedDict


class NewsItem(TypedDict):
    """A parsed news item and the optional fields added by later stages."""

    zh_title: str
    content: str
    source_url: str
    en_title: NotRequired[str]
    pubdate: NotRequired[str]
    en_content: NotRequired[str]
    scrape_succeeded: NotRequired[bool]
    subcategory: NotRequired[str]
    classification_succeeded: NotRequired[bool]


class ScrapedFields(TypedDict):
    """Fields returned by the source scraper before merging into a news item."""

    en_title: str
    pubdate: str
    en_content: str
    scrape_succeeded: bool
