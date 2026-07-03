import unittest
from unittest.mock import patch

from services.scraper import _extract_article, scrape_article


class FakeResponse:
    text = """
        <html>
            <head>
                <title>Carbon market update - Example</title>
                <meta property="article:published_time" content="2026-05-31T12:00:00Z">
            </head>
            <body>
                <p>This paragraph is long enough to be included as article content for the report.</p>
                <p>This second paragraph makes the static HTML article long enough to avoid browser fallback.</p>
            </body>
        </html>
    """
    apparent_encoding = "utf-8"
    encoding = None
    headers = {}
    is_redirect = False

    def raise_for_status(self):
        return None


class ShortResponse(FakeResponse):
    text = """
        <html>
            <head><title>Short article - Example</title></head>
            <body><p>Short paragraph with enough characters.</p></body>
        </html>
    """


class FakeSession:
    def get(self, url, headers, timeout, allow_redirects):
        return FakeResponse()


class ShortSession:
    def get(self, url, headers, timeout, allow_redirects):
        return ShortResponse()


class FailingSession:
    def get(self, url, headers, timeout, allow_redirects):
        raise RuntimeError("requests failed")


class RedirectResponse:
    headers = {"Location": "http://127.0.0.1/admin"}
    is_redirect = True


class RedirectSession:
    def get(self, url, headers, timeout, allow_redirects):
        return RedirectResponse()


class ScraperTests(unittest.TestCase):
    def test_extract_article_uses_json_ld_article_body(self):
        result = _extract_article(
            '''
            <html><head><script type="application/ld+json">
            {"@type":"NewsArticle","headline":"Structured headline",
             "datePublished":"2026-06-14T08:00:00Z",
             "articleBody":"This structured article body contains enough useful text for extraction. This second sentence ensures the content passes the minimum length required by the scraper."}
            </script></head><body></body></html>
            '''
        )

        self.assertEqual(result["en_title"], "Structured headline")
        self.assertEqual(result["pubdate"], "2026-06-14")
        self.assertTrue(result["scrape_succeeded"])

    def test_extract_article_preserves_content_longer_than_4000_characters(self):
        article_body = ("Complete English article paragraph. " * 200).strip()
        result = _extract_article(
            f'''
            <html><head><script type="application/ld+json">
            {{"@type":"NewsArticle","headline":"Long article",
              "datePublished":"2026-06-14T08:00:00Z",
              "articleBody":"{article_body}"}}
            </script></head><body></body></html>
            '''
        )

        self.assertGreater(len(article_body), 4000)
        self.assertEqual(result["en_content"], article_body)
        self.assertTrue(result["scrape_succeeded"])

    def test_extract_article_does_not_guess_unrelated_date(self):
        result = _extract_article(
            """
            <html><head>
              <meta property="article:modified_time" content="2026-06-20T08:00:00Z">
              <script type="application/ld+json">
                {"@type":"Event","datePublished":"2026-06-18T08:00:00Z",
                 "startDate":"2027-03-15T09:00:00Z"}
              </script>
              <title>Article without a published date</title>
            </head><body>
              <article><p>This article mentions an unrelated event scheduled for 2027-03-15,
              but the page does not provide a trustworthy publication date for the article.</p></article>
            </body></html>
            """
        )

        self.assertEqual(result["pubdate"], "")

    def test_extract_article_uses_semantic_published_time(self):
        result = _extract_article(
            """
            <html><head><title>Semantic date article</title></head>
            <body><article>
              <time itemprop="datePublished" datetime="2026-07-02T09:30:00+08:00"></time>
              <p>This article contains enough meaningful text to pass the minimum article
              content length and verify semantic publication date extraction correctly.</p>
            </article></body></html>
            """
        )

        self.assertEqual(result["pubdate"], "2026-07-02")

    def test_scrape_article_skips_empty_url(self):
        result = scrape_article(FakeSession(), "")

        self.assertFalse(result["scrape_succeeded"])
        self.assertEqual(result["en_content"], "來源資料沒有網址，請手動確認原文。")

    @patch("services.scraper.validate_public_url")
    def test_scrape_article_extracts_expected_fields(self, validate_public_url):
        result = scrape_article(FakeSession(), "https://www.example.com/news/1")

        self.assertEqual(result["en_title"], "Carbon market update")
        self.assertEqual(result["pubdate"], "2026-05-31")
        self.assertIn("long enough", result["en_content"])

    @patch("services.scraper._scrape_with_playwright")
    @patch("services.scraper.validate_public_url")
    def test_scrape_article_uses_playwright_when_requests_content_is_short(
        self, validate_public_url, scrape_with_playwright
    ):
        scrape_with_playwright.return_value = {
            "en_title": "Rendered title",
            "pubdate": "2026-06-05",
            "en_content": "Rendered article content " * 10,
            "scrape_succeeded": True,
        }

        result = scrape_article(ShortSession(), "https://www.example.com/news/1")

        self.assertEqual(result["en_title"], "Rendered title")
        scrape_with_playwright.assert_called_once_with("https://www.example.com/news/1", 15)

    @patch("services.scraper._scrape_with_playwright")
    @patch("services.scraper.validate_public_url")
    def test_scrape_article_uses_playwright_when_requests_fails(
        self, validate_public_url, scrape_with_playwright
    ):
        scrape_with_playwright.return_value = {
            "en_title": "Rendered title",
            "pubdate": "2026-06-05",
            "en_content": "Rendered article content " * 10,
            "scrape_succeeded": True,
        }

        result = scrape_article(FailingSession(), "https://www.example.com/news/1")

        self.assertTrue(result["scrape_succeeded"])
        scrape_with_playwright.assert_called_once_with("https://www.example.com/news/1", 15)

    @patch("services.scraper.validate_public_url")
    def test_scrape_article_returns_failure_when_url_is_rejected(self, validate_public_url):
        validate_public_url.side_effect = ValueError("來源網址不可指向內部網路")
        result = scrape_article(FakeSession(), "https://www.example.com/news/1")

        self.assertFalse(result["scrape_succeeded"])
        self.assertEqual(result["en_title"], "Fetch Failed (請手動確認)")
        self.assertEqual(result["pubdate"], "")
        self.assertEqual(result["en_content"], "無法自動爬取原文，請手動確認來源網址。")

    @patch("services.scraper.validate_public_url")
    def test_scrape_article_validates_redirect_target(self, validate_public_url):
        validate_public_url.side_effect = [None, ValueError("來源網址不可指向內部網路")]

        result = scrape_article(RedirectSession(), "https://www.example.com/news/1")

        self.assertFalse(result["scrape_succeeded"])
        self.assertGreaterEqual(validate_public_url.call_count, 2)


if __name__ == "__main__":
    unittest.main()
