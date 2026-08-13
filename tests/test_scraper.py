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


class CorruptResponse(FakeResponse):
    text = f"<html><body><article><p>{'�' * 300}</p></article></body></html>"


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


class FakeNavigationRequest:
    def __init__(self, url, navigation=True):
        self.url = url
        self._navigation = navigation

    def is_navigation_request(self):
        return self._navigation


class FakeRoute:
    def __init__(self, request, sent_urls, aborted_urls):
        self.request = request
        self._sent_urls = sent_urls
        self._aborted_urls = aborted_urls
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True
        self._aborted_urls.append(self.request.url)

    def continue_(self):
        self.continued = True
        self._sent_urls.append(self.request.url)


class FakePlaywrightPage:
    def __init__(self, context, sent_urls, aborted_urls):
        self._context = context
        self._sent_urls = sent_urls
        self._aborted_urls = aborted_urls
        self.url = ""

    def add_init_script(self, script):
        return None

    def goto(self, url, wait_until, timeout):
        self.url = url
        self._navigate(url)
        for resource_url in (
            "http://127.0.0.1/private.png",
            "https://93.184.216.34/public.js",
            "data:image/png;base64,AAAA",
        ):
            self._navigate(resource_url, navigation=False)
        redirect_url = "http://127.0.0.1/admin"
        self._navigate(redirect_url)
        raise RuntimeError("private navigation would reach the browser")

    def _navigate(self, url, navigation=True):
        handler = self._context.route_handlers.get("**/*")
        if handler is None:
            self._sent_urls.append(url)
            return

        route = FakeRoute(
            FakeNavigationRequest(url, navigation=navigation),
            self._sent_urls,
            self._aborted_urls,
        )
        handler(route)
        if not route.aborted and not route.continued:
            self._sent_urls.append(url)

    def wait_for_load_state(self, state, timeout):
        return None

    def wait_for_timeout(self, timeout):
        return None

    def query_selector(self, selector):
        return None

    def content(self):
        return "<html><body></body></html>"


class FakePlaywrightContext:
    def __init__(self, sent_urls, aborted_urls):
        self.route_handlers = {}
        self._sent_urls = sent_urls
        self._aborted_urls = aborted_urls
        self.new_context_kwargs = None

    def route(self, pattern, handler):
        self.route_handlers[pattern] = handler

    def new_page(self):
        return FakePlaywrightPage(self, self._sent_urls, self._aborted_urls)


class FakePlaywrightBrowser:
    def __init__(self, sent_urls, aborted_urls):
        self._sent_urls = sent_urls
        self._aborted_urls = aborted_urls
        self.context = None

    def new_context(self, **kwargs):
        self.context = FakePlaywrightContext(self._sent_urls, self._aborted_urls)
        self.context.new_context_kwargs = kwargs
        return self.context

    def close(self):
        return None


class FakePlaywrightChromium:
    def __init__(self, sent_urls, aborted_urls):
        self._sent_urls = sent_urls
        self._aborted_urls = aborted_urls
        self.browser = None

    def launch(self, **kwargs):
        self.browser = FakePlaywrightBrowser(self._sent_urls, self._aborted_urls)
        return self.browser


class FakePlaywrightSdk:
    def __init__(self, sent_urls, aborted_urls):
        self.chromium = FakePlaywrightChromium(sent_urls, aborted_urls)


class FakeSyncPlaywright:
    def __init__(self, sent_urls, aborted_urls):
        self.sdk = FakePlaywrightSdk(sent_urls, aborted_urls)

    def __enter__(self):
        return self.sdk

    def __exit__(self, exc_type, exc_value, traceback):
        return False


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

    def test_extract_article_rejects_block_page_even_when_text_is_long(self):
        result = _extract_article(
            """
            <html><head><title>Just a moment...</title></head><body>
              <p>Checking your browser before accessing this site.</p>
              <p>This process is automatic. Verification successful. Waiting for the website
              to respond. Enable JavaScript and cookies to continue. This extra text makes the
              response longer than the normal minimum article content threshold.</p>
            </body></html>
            """,
            url="https://www.example.com/protected",
        )

        self.assertFalse(result["scrape_succeeded"])
        self.assertEqual(result["en_title"], "")
        self.assertIn("驗證或拒絕存取", result["en_content"])

    def test_extract_article_prefers_open_graph_title(self):
        result = _extract_article(
            """
            <html><head>
              <title>Publisher brand - Site</title>
              <meta property="og:title" content="Complete article headline: policy update">
            </head><body><article>
              <h1>Short page heading</h1>
              <p>This article contains enough meaningful policy reporting to pass the minimum
              content threshold, while confirming that the Open Graph headline is preferred.</p>
            </article></body></html>
            """
        )

        self.assertEqual(result["en_title"], "Complete article headline: policy update")

    def test_extract_article_prefers_h1_over_document_title(self):
        result = _extract_article(
            """
            <html><head><title>Dentons - Global legal insights</title></head><body><main>
              <h1>Carbon market reform in Quebec</h1>
              <p>This article contains enough meaningful legal and carbon market reporting to
              pass the minimum content threshold and verify the page heading selection order.</p>
            </main></body></html>
            """
        )

        self.assertEqual(result["en_title"], "Carbon market reform in Quebec")

    def test_extract_article_removes_navigation_and_template_noise(self):
        result = _extract_article(
            """
            <html><head><title>Market update - Publisher</title></head><body>
              <header><p>Methodology Contact us Support Login Share Prices Stock Tips</p></header>
              <nav><p>Home Markets News Subscribe Account Settings</p></nav>
              <main><article><h1>Market update</h1>
                <p>{{suggestionHead.categoryName}} The carbon market authority published a
                detailed reform proposal covering allowance supply and compliance obligations.</p>
                <p>The proposal also explains implementation timing, stakeholder consultation,
                and safeguards intended to preserve market integrity and investment certainty.</p>
              </article></main>
              <footer><p>Privacy Terms Contact us Newsletter Login</p></footer>
            </body></html>
            """
        )

        self.assertTrue(result["scrape_succeeded"])
        self.assertNotIn("Methodology Contact us", result["en_content"])
        self.assertNotIn("suggestionHead", result["en_content"])
        self.assertNotIn("Privacy Terms", result["en_content"])
        self.assertIn("detailed reform proposal", result["en_content"])

    def test_scrape_article_skips_empty_url(self):
        result = scrape_article(FakeSession(), "")

        self.assertFalse(result["scrape_succeeded"])
        self.assertEqual(result["en_content"], "來源資料沒有網址，請手動確認原文。")

    @patch("services.scraper.validate_public_url")
    def test_scrape_article_extracts_expected_fields(self, validate_public_url):
        session = FakeSession()
        with patch.object(session, "get", wraps=session.get) as get:
            result = scrape_article(session, "https://www.example.com/news/1")

        self.assertEqual(result["en_title"], "Carbon market update")
        self.assertEqual(result["pubdate"], "2026-05-31")
        self.assertIn("long enough", result["en_content"])
        self.assertNotIn("br", get.call_args.kwargs["headers"].get("Accept-Encoding", ""))

    @patch("services.scraper._scrape_with_playwright")
    @patch("services.scraper.validate_public_url")
    def test_scrape_article_uses_playwright_when_requests_content_is_corrupt(
        self, validate_public_url, scrape_with_playwright
    ):
        scrape_with_playwright.return_value = {
            "en_title": "Rendered title",
            "pubdate": "2026-07-31",
            "en_content": "Rendered article content " * 10,
            "scrape_succeeded": True,
        }

        session = FakeSession()
        with patch.object(session, "get", return_value=CorruptResponse()):
            result = scrape_article(session, "https://www.example.com/news/1")

        self.assertEqual(result["en_title"], "Rendered title")
        scrape_with_playwright.assert_called_once_with("https://www.example.com/news/1", 15)

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

    def test_scrape_article_blocks_private_playwright_redirects(self):
        public_url = "https://www.example.com/news/1"
        private_url = "http://127.0.0.1/admin"
        sent_urls = []
        aborted_urls = []
        fake_playwright = FakeSyncPlaywright(sent_urls, aborted_urls)

        with patch("services.scraper.sync_playwright", return_value=fake_playwright):
            result = scrape_article(FailingSession(), public_url)

        self.assertEqual(
            result,
            {
                "en_title": "",
                "pubdate": "",
                "en_content": "無法自動爬取原文，請手動確認來源網址。",
                "scrape_succeeded": False,
            },
        )
        self.assertIn(public_url, sent_urls)
        self.assertNotIn(private_url, sent_urls)
        self.assertIn(private_url, aborted_urls)

    def test_scrape_article_blocks_private_playwright_subresources(self):
        public_url = "https://www.example.com/news/1"
        private_resource_url = "http://127.0.0.1/private.png"
        public_resource_url = "https://93.184.216.34/public.js"
        data_resource_url = "data:image/png;base64,AAAA"
        sent_urls = []
        aborted_urls = []
        fake_playwright = FakeSyncPlaywright(sent_urls, aborted_urls)

        with patch("services.scraper.sync_playwright", return_value=fake_playwright):
            result = scrape_article(FailingSession(), public_url)

        self.assertEqual(
            result,
            {
                "en_title": "",
                "pubdate": "",
                "en_content": "無法自動爬取原文，請手動確認來源網址。",
                "scrape_succeeded": False,
            },
        )
        self.assertIn(public_url, sent_urls)
        self.assertNotIn(private_resource_url, sent_urls)
        self.assertIn(private_resource_url, aborted_urls)
        self.assertIn(public_resource_url, sent_urls)
        self.assertIn(data_resource_url, sent_urls)

    @patch("services.scraper.validate_public_url")
    def test_scrape_article_returns_failure_when_url_is_rejected(self, validate_public_url):
        validate_public_url.side_effect = ValueError("來源網址不可指向內部網路")
        result = scrape_article(FakeSession(), "https://www.example.com/news/1")

        self.assertFalse(result["scrape_succeeded"])
        self.assertEqual(result["en_title"], "")
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
