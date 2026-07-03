import logging
import json
import re
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from services.url_security import validate_public_url


logger = logging.getLogger(__name__)
MAX_REDIRECTS = 5
MIN_CONTENT_LENGTH = 120
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
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
        "en_title": "Fetch Failed (請手動確認)",
        "pubdate": "",
        "en_content": message,
        "scrape_succeeded": False,
    }


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


def _extract_article(html, url=""):
    soup = BeautifulSoup(html, "html.parser")
    result = {"en_title": "", "pubdate": "", "en_content": "", "scrape_succeeded": False}

    structured_articles = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph", [])
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
            if candidate.get("articleBody"):
                structured_articles.append(candidate)

    structured_article = structured_articles[0] if structured_articles else {}

    if structured_article.get("headline"):
        result["en_title"] = str(structured_article["headline"]).strip()
    elif soup.title and soup.title.string:
        result["en_title"] = re.split(r" - | \| |: ", soup.title.string.strip())[0]
    elif soup.find("h1"):
        result["en_title"] = soup.find("h1").text.strip()
    else:
        result["en_title"] = "Click Link to View Original Title"

    # 修正：meta_date 在 else 外部使用，必須預先初始化避免 NameError
    meta_date = None
    if structured_article.get("datePublished"):
        result["pubdate"] = str(structured_article["datePublished"])[:10]
    else:
        meta_date = soup.find("meta", property="article:published_time")
    if not result["pubdate"] and meta_date and meta_date.get("content"):
        result["pubdate"] = meta_date["content"][:10]
    elif not result["pubdate"]:
        date_match = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", html)
        result["pubdate"] = date_match.group(0).replace("/", "-") if date_match else ""

    text_content = ""

    # 優先：JSON-LD articleBody（最完整）
    if structured_article.get("articleBody"):
        text_content = str(structured_article["articleBody"]).strip()

    # 次選：trafilatura（處理 div 段落、JS 渲染後的各類版面）
    if len(text_content) < MIN_CONTENT_LENGTH:
        try:
            extracted = trafilatura.extract(
                html,
                url=url or None,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
            )
            if extracted and len(extracted) >= MIN_CONTENT_LENGTH:
                text_content = extracted
        except Exception:
            pass

    # 備用：BeautifulSoup 抓 <p> 段落
    if len(text_content) < MIN_CONTENT_LENGTH:
        article_root = soup.find("article") or soup.find("main")
        paragraphs = article_root.find_all("p") if article_root else soup.find_all("p")
        para_texts = [
            p.get_text(" ", strip=True)
            for p in paragraphs
            if len(p.get_text(" ", strip=True)) > 30
        ]
        text_content = " ".join(para_texts)

    # 最後：meta description 兜底
    if len(text_content) < MIN_CONTENT_LENGTH:
        description = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", property="og:description"
        )
        if description and description.get("content"):
            text_content = description["content"].strip()

    result["en_content"] = text_content or "無法辨識內文段落，請點擊連結查看網頁。"
    result["scrape_succeeded"] = len(text_content) >= MIN_CONTENT_LENGTH
    return result


def _scrape_with_requests(session, url, timeout):
    response = _get_public_response(session, url, DEFAULT_HEADERS, timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return _extract_article(response.text, url=url)


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
