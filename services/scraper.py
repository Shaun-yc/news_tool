import logging
import json
import re
from datetime import datetime
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from services.url_security import validate_public_url


logger = logging.getLogger(__name__)
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
MAX_REDIRECTS = 5
MIN_CONTENT_LENGTH = 120
_BLOCK_PAGE_TITLE_MARKERS = (
    "just a moment",
    "access denied",
    "attention required",
    "security verification",
)
_BLOCK_PAGE_TEXT_MARKERS = (
    "checking your browser before accessing",
    "performing security verification",
    "enable javascript and cookies to continue",
    "verify you are not a bot",
    "protect against malicious bots",
    "you don't have permission to access",
)
_CONTENT_NOISE_TAGS = (
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "dialog",
    "noscript",
    "script",
    "style",
    "svg",
)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Playwright 啟動參數：隱藏自動化特徵
_PLAYWRIGHT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# 注入 script：移除 navigator.webdriver 旗標，防止反爬蟲偵測
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
"""

# Cookie 同意彈窗常見的接受按鈕選擇器
_COOKIE_ACCEPT_SELECTORS = [
    "button[id*='accept']",
    "button[class*='accept']",
    "button[id*='agree']",
    "button[class*='agree']",
    "button[id*='consent']",
    "[aria-label*='Accept']",
    "[aria-label*='agree']",
]


def _failure_result(message="無法自動爬取原文，請手動確認來源網址。"):
    return {
        "en_title": "",
        "pubdate": "",
        "en_content": message,
        "scrape_succeeded": False,
    }


def _is_block_page(soup):
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    page_text = soup.get_text(" ", strip=True).lower()
    return any(marker in title for marker in _BLOCK_PAGE_TITLE_MARKERS) or any(
        marker in page_text for marker in _BLOCK_PAGE_TEXT_MARKERS
    )


def _extract_page_title(soup, structured_article):
    structured_headline = structured_article.get("headline")
    if structured_headline:
        return str(structured_headline).strip()

    for attributes in ({"property": "og:title"}, {"name": "twitter:title"}):
        element = soup.find("meta", attrs=attributes)
        if element and element.get("content"):
            return element["content"].strip()

    heading = soup.find("h1")
    if heading:
        heading_text = heading.get_text(" ", strip=True)
        if heading_text:
            return heading_text

    if soup.title:
        raw_title = soup.title.get_text(" ", strip=True)
        title_parts = [part.strip() for part in re.split(r"\s+(?:[-|–—])\s+", raw_title) if part.strip()]
        if title_parts:
            return max(title_parts, key=len)
    return ""


def _prepare_content_soup(soup):
    content_soup = BeautifulSoup(str(soup), "html.parser")
    for element in content_soup.find_all(_CONTENT_NOISE_TAGS):
        element.decompose()
    for text_node in content_soup.find_all(string=re.compile(r"{{.*?}}")):
        cleaned = re.sub(r"{{.*?}}", "", str(text_node))
        text_node.replace_with(cleaned)
    return content_soup


def _clean_article_text(text):
    cleaned_lines = []
    for line in str(text or "").splitlines():
        cleaned = re.sub(r"{{.*?}}", "", line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines)


def _has_excessive_decode_errors(text):
    text = str(text or "")
    return text.count("\ufffd") > max(3, len(text) // 100)


def _get_public_response(session, url, headers, timeout):
    for _ in range(MAX_REDIRECTS + 1):
        validate_public_url(url)
        response = session.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        if not response.is_redirect:
            return response
        location = response.headers.get("Location")
        if not location:
            raise ValueError("來源網站重新導向缺少目標網址")
        url = urljoin(url, location)
    raise ValueError("來源網站重新導向次數過多")


def _normalize_published_date(value):
    match = re.match(r"^\s*(\d{4})[-/](\d{2})[-/](\d{2})", str(value or ""))
    if not match:
        return ""
    normalized = "-".join(match.groups())
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError:
        return ""
    return normalized


def _extract_published_date(soup, structured_candidates):
    # 結構化新聞資料的 datePublished 可信度最高；刻意不採用 dateModified。
    for candidate in structured_candidates:
        candidate_types = candidate.get("@type", [])
        if isinstance(candidate_types, str):
            candidate_types = [candidate_types]
        is_article = bool(candidate.get("articleBody")) or any(
            article_type in {
                "Article",
                "NewsArticle",
                "AnalysisNewsArticle",
                "ReportageNewsArticle",
                "BlogPosting",
            }
            for article_type in candidate_types
        )
        if not is_article:
            continue
        published_date = _normalize_published_date(candidate.get("datePublished"))
        if published_date:
            return published_date

    meta_selectors = [
        ("property", "article:published_time"),
        ("itemprop", "datePublished"),
        ("name", "parsely-pub-date"),
        ("name", "pub_date"),
        ("name", "publishdate"),
        ("name", "datePublished"),
    ]
    for attribute, value in meta_selectors:
        element = soup.find("meta", attrs={attribute: value})
        if element:
            published_date = _normalize_published_date(element.get("content"))
            if published_date:
                return published_date

    time_element = soup.find("time", attrs={"itemprop": "datePublished"})
    if not time_element:
        time_element = soup.find(
            "time",
            class_=re.compile(r"\b(?:publish|published|posted)(?:[-_\s]|$)", re.IGNORECASE),
        )
    if time_element:
        return _normalize_published_date(
            time_element.get("datetime") or time_element.get_text(" ", strip=True)
        )
    return ""


def _extract_article(html, url=""):
    soup = BeautifulSoup(html, "html.parser")
    result = {"en_title": "", "pubdate": "", "en_content": "", "scrape_succeeded": False}

    if _is_block_page(soup):
        logger.warning("Blocked or verification page detected for URL %s", url or "<unknown>")
        return _failure_result("來源網站顯示驗證或拒絕存取頁面，請手動確認原文。")

    structured_articles = []
    structured_candidates = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            structured_candidates.append(candidate)
            graph = candidate.get("@graph", [])
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
            if candidate.get("articleBody"):
                structured_articles.append(candidate)

    structured_article = structured_articles[0] if structured_articles else {}

    result["en_title"] = _extract_page_title(soup, structured_article)

    result["pubdate"] = _extract_published_date(soup, structured_candidates)
    content_soup = _prepare_content_soup(soup)
    cleaned_html = str(content_soup)

    text_content = ""

    # 優先：JSON-LD articleBody（最完整）
    if structured_article.get("articleBody"):
        text_content = _clean_article_text(structured_article["articleBody"])

    # 次選：trafilatura（處理 div 段落、JS 渲染後的各類版面）
    if len(text_content) < MIN_CONTENT_LENGTH:
        try:
            extracted = trafilatura.extract(
                cleaned_html,
                url=url or None,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
            )
            extracted = _clean_article_text(extracted)
            if len(extracted) >= MIN_CONTENT_LENGTH:
                text_content = extracted
        except Exception:
            pass

    # 備用：BeautifulSoup 抓 <p> 段落
    if len(text_content) < MIN_CONTENT_LENGTH:
        article_root = content_soup.find("article") or content_soup.find("main")
        paragraphs = article_root.find_all("p") if article_root else content_soup.find_all("p")
        para_texts = [
            p.get_text(" ", strip=True)
            for p in paragraphs
            if len(p.get_text(" ", strip=True)) > 30
        ]
        text_content = _clean_article_text("\n".join(para_texts))

    # 最後：meta description 兜底
    if len(text_content) < MIN_CONTENT_LENGTH:
        description = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", property="og:description"
        )
        if description and description.get("content"):
            text_content = _clean_article_text(description["content"])

    text_content = _clean_article_text(text_content)
    result["en_content"] = text_content or "無法辨識內文段落，請點擊連結查看網頁。"
    result["scrape_succeeded"] = len(text_content) >= MIN_CONTENT_LENGTH
    if not result["scrape_succeeded"]:
        result["en_title"] = ""
    return result


def _scrape_with_requests(session, url, timeout):
    response = _get_public_response(session, url, DEFAULT_HEADERS, timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    response_text = response.text
    if _has_excessive_decode_errors(response_text):
        raise ValueError("來源網站回應包含無法解碼的內容")
    return _extract_article(response_text, url=url)


def _dismiss_cookie_consent(page):
    """嘗試點擊 Cookie 同意彈窗的接受按鈕。"""
    for selector in _COOKIE_ACCEPT_SELECTORS:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def _scrape_with_playwright(url, timeout):
    validate_public_url(url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=_PLAYWRIGHT_ARGS,
        )
        try:
            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                locale="en-US",
                extra_http_headers={
                    "Accept": DEFAULT_HEADERS["Accept"],
                    "Accept-Language": DEFAULT_HEADERS["Accept-Language"],
                },
            )
            page = context.new_page()
            # 注入 stealth script，在每個頁面載入前執行
            page.add_init_script(_STEALTH_SCRIPT)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            validate_public_url(page.url)
            # 等待 JS 渲染；networkidle 超時則等固定時間
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                page.wait_for_timeout(2000)
            _dismiss_cookie_consent(page)
            html = page.content()
        finally:
            browser.close()
    return _extract_article(html, url=url)


def scrape_article(session, url, timeout=7):
    """Fetch the English title, publication date, and article body from a URL."""
    if not url or not url.strip():
        logger.info("Article has no source URL; skipping web scraping")
        return _failure_result("來源資料沒有網址，請手動確認原文。")

    try:
        result = _scrape_with_requests(session, url, timeout)
        if result["scrape_succeeded"]:
            return result
        logger.warning("Article content too short from requests; using Playwright fallback for URL %s", url)
    except Exception as error:
        logger.warning("Requests article scraping failed for URL %s: %s", url, error)

    try:
        result = _scrape_with_playwright(url, max(timeout, 15))
        if result["scrape_succeeded"]:
            return result
        logger.warning("Playwright article content too short for URL %s", url)
        return result
    except Exception as error:
        logger.warning("Playwright article scraping failed for URL %s: %s", url, error)
        return _failure_result()
