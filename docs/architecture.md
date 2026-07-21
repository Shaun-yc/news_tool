# news_tool Architecture

## 概覽

`news_tool` 是週新聞彙整工具。它從 `.docx` 週新聞檔解析中文標題、中文摘要與來源 URL，擷取來源網頁的英文標題、發布日期與內文，使用 vLLM 相容的 `/v1/chat/completions` API 進行氣候議題分類及固定標籤摘要對齊，最後輸出標準 14 欄 Excel。

系統提供兩個入口：

- `app.py`：Streamlit 互動介面，供人工上傳 Word 檔並下載 Excel。
- `api.py`：FastAPI REST API，提供 `POST /process` 給自動化流程呼叫。

## 架構分層

```text
Presentation / API
  app.py                       Streamlit UI
  api.py                       FastAPI: GET /health, POST /process

Application / Orchestration
  services/report_service.py   Word/report workflow wrapper
  services/processor.py        scrape -> classify -> summary alignment orchestration

Domain Services
  services/word_parser.py      .docx parsing
  services/scraper.py          requests-first web scraping with Playwright fallback
  services/classifier.py       vLLM classification, tag normalization, summary alignment
  services/summarizer.py       unused legacy summary helper (not in the main flow)
  services/excel_exporter.py   14-column Excel export
  services/audit_archive.py    input/output/metadata audit retention
  services/url_security.py     public URL validation before network access

Configuration
  services/config.py           environment variables -> frozen Settings dataclass
```

## 主要資料流

### Streamlit UI

```text
app.py
  -> word_parser.parse_word_news(uploaded_file)
  -> report_service.build_report_from_news_list(news_list, filename, settings)
       -> processor.process_news(news_list, settings,
              on_scrape_progress=..., on_classify_progress=...)
            -> scraper.scrape_article(session, source_url, timeout)
            -> classifier.classify_news(...)
            -> classifier.align_summary_to_tags(...) when classification succeeds
       -> excel_exporter.build_excel_report(news_list, week_date)
  -> audit_archive.archive_report(input_bytes, output_bytes, metadata)
  -> st.download_button(...)
```

### FastAPI

```text
api.py POST /process
  -> report_service.build_weekly_news_report(file.file, file.filename, get_settings())
       -> word_parser.parse_word_news(file_object)
       -> report_service.build_report_from_news_list(news_list, filename, settings)
            -> processor.process_news(...)
                 -> scrape -> classify -> summary alignment
            -> excel_exporter.build_excel_report(...)
  -> audit_archive.archive_report(input_bytes, output_bytes, metadata)
  -> StreamingResponse(.xlsx)
```

`build_report_from_news_list()` 接收已解析的 `news_list`；`build_weekly_news_report()` 是 API 使用的單檔 wrapper，負責先 parse Word 再轉呼叫 `build_report_from_news_list()`。

## 模組職責

### `services/word_parser.py`

- 使用 `python-docx` 解析 `.docx`。
- 輸出新聞項目 list，每筆包含 `zh_title`、`content`、`source_url`。
- 不負責網路存取或 URL 安全檢查。

### `services/url_security.py`

- 主要函式：`validate_public_url()`。
- 驗證外部 URL 是否可供公開網路存取，避免 SSRF 風險。
- 目前由 scraper 在實際發出 HTTP/Browser request 前呼叫；redirect 後的目標 URL 也會重新驗證。

### `services/scraper.py`

- 主要函式：`scrape_article(session, url, timeout=7)`。
- 空 URL 會直接回傳失敗結果，不進行網路請求。
- 優先使用 `requests`，透過 `_get_public_response()` 手動處理 redirect，最多 `MAX_REDIRECTS = 5` 次，且每次請求前都呼叫 `validate_public_url()`。
- 若 requests 擷取失敗或內容不足，fallback 到 Playwright。
- Playwright 會：
  - 使用 headless Chromium。
  - 加入簡單 stealth script。
  - 嘗試關閉 cookie consent。
  - 在 `page.goto()` 後再次驗證 `page.url`。
- `_extract_article()` 的內文擷取順序：
  1. JSON-LD `articleBody`
  2. `trafilatura.extract()` 從目前 HTML 擷取正文
  3. BeautifulSoup 擷取 `<article>` / `<main>` / 全頁 `<p>`
  4. meta description / `og:description`
- 發布日期只從較高可信來源擷取，例如 JSON-LD `datePublished`、特定 meta tags、語意明確的 `<time>`；刻意不使用 `dateModified` 或頁面第一個日期猜測。
- scraper 不會任意截斷 `en_content`。Excel 本身有單格長度限制，若未來需要截斷或保留策略，應在 exporter 或報表層明確實作。

### `services/classifier.py`

- 主要函式：`classify_news()`。
- 使用 vLLM 相容的 `/v1/chat/completions` endpoint。
- `_build_prompt()` 使用中文標題與中文摘要作為主要判斷依據，英文原文證據作為補充。
- `_select_english_evidence()` 會把英文證據限制在 `MAX_ENGLISH_EVIDENCE_CHARS = 6000` 字元內，採前段與後段保留。
- `normalize_tags()` 接受白名單中的 1 到 3 個標籤；單一核心主題允許 1 個，超過 3 個會取前 3 個，沒有有效標籤或 `NONE` 會回傳 `None`。
- vLLM `requests.RequestException` 會啟動 `VLLM_UNAVAILABLE_COOLDOWN_SECONDS = 300` 秒 cooldown；cooldown 期間分類直接回傳 `REVIEW_REQUIRED, False`。
- 分類失敗、無效標籤、`NONE` 或 cooldown 都不會中斷整批流程，而是標記為待人工確認。
- `align_summary_to_tags()` 只在分類成功後執行，使用主模型與已固定的標籤重新檢查中文摘要。
- 摘要對齊不得改動標籤或杜撰來源沒有的資訊；模型回傳 `KEEP_ORIGINAL`、輸出少於 120 或超過 500 字、呼叫失敗時都保留原摘要。

### `services/processor.py`

- 主要函式：`process_news()`。
- 對整批 `news_list` 執行兩個 sequential loops，第二個 loop 內含條件式摘要對齊：
  1. Scrape phase：呼叫 `scrape_article()`，填入 `en_title`、`pubdate`、`en_content`、`scrape_succeeded`。
  2. Classify phase：呼叫 `classify_news()`，填入 `subcategory`、`classification_succeeded`；成功時接著呼叫 `align_summary_to_tags()`，必要時更新 `content`。
- 若 scrape 失敗，不會把失敗訊息當英文證據送入分類 prompt。
- 回傳 `ProcessingSummary(total_count, scrape_failed_count, classification_fallback_count, summary_aligned_count)`。

### `services/report_service.py`

- `get_week_date(filename)`：從檔名中的 `YYYY.MM.DD` 擷取週日期，找不到時使用目前日期。
- `build_report_from_news_list(news_list, filename, settings, **process_kwargs)`：
  - 驗證 `news_list` 非空。
  - 呼叫 `process_news()` enrich 資料。
  - 呼叫 `build_excel_report()` 輸出 Excel。
- `build_weekly_news_report(file_object, filename, settings, **process_kwargs)`：
  - API 使用的 wrapper。
  - 先呼叫 `parse_word_news()`，再呼叫 `build_report_from_news_list()`。

### `services/excel_exporter.py`

- 主要函式：`build_excel_report(news_list, week_date)`。
- 使用 `openpyxl` 建立 14 欄標準格式 Excel。
- 回傳 in-memory `BytesIO`，供 Streamlit 下載或 FastAPI `StreamingResponse` 使用。
- `_sanitize()` 移除非法 XML 字元，但目前不截斷字串。

### `services/config.py`

- 使用 `@dataclass(frozen=True)` 定義 `Settings`。
- `get_settings()` 從環境變數讀取設定。
- 若環境變數不存在，會使用程式內 fallback 預設值。這些預設值與 `.env.example` 對齊，但可能不適合所有部署環境。
- `CLASSIFY_BASE_URL`／`CLASSIFY_MODEL` 供分類使用，缺少時退回主模型；摘要對齊使用 `VLLM_BASE_URL`／`VLLM_MODEL` 與 `SUMMARY_ALIGN_MAX_TOKENS`。
- `VLLM_MAX_TOKENS` 仍會載入 `Settings`，但目前主流程沒有把它傳入任何模型呼叫。

### `services/audit_archive.py`

- Streamlit 與 FastAPI 在報告成功產出後，保存 `input.docx`、`output.xlsx` 與 `metadata.json`。
- 每筆資料夾以 UTC 時間與輸入檔 SHA-256 前綴命名，避免同名或併發處理互相覆蓋。
- 稽核寫入失敗只記錄 log，不阻斷使用者下載。
- 每次新增稽核資料時，清除超過 `AUDIT_RETENTION_DAYS` 的舊資料夾。

## 設定

主要環境變數：

```text
VLLM_BASE_URL
VLLM_MODEL
VLLM_TIMEOUT_SECONDS
VLLM_TEMPERATURE
VLLM_MAX_TOKENS

CLASSIFY_BASE_URL
CLASSIFY_MODEL
CLASSIFY_MAX_TOKENS
SUMMARY_ALIGN_MAX_TOKENS

SCRAPE_DELAY_SECONDS
CLASSIFY_DELAY_SECONDS
REQUEST_TIMEOUT_SECONDS

AUDIT_ARCHIVE_DIR
AUDIT_RETENTION_DAYS
```

分類專用設定未提供時，`CLASSIFY_BASE_URL` 與 `CLASSIFY_MODEL` 會 fallback 到主模型設定。

## 部署

- Docker 使用單一 container。
- `start.sh` 在同一個 container 內啟動兩個程序：
  - `uvicorn api:app --host 0.0.0.0 --port 8001 &`
  - `streamlit run app.py`
- `docker-compose.yml` 對外暴露：
  - `8001`：FastAPI
  - `8501`：Streamlit
- `Dockerfile` healthcheck 呼叫 `http://127.0.0.1:8001/health`。
- `docker-compose.yml` 將主機 `./audit` 掛載到容器 `/app/audit`，容器重建後仍保留稽核檔案。

## 測試結構

測試位於 `tests/`，主要對應 service 模組：

- `tests/test_api.py`
- `tests/test_classifier.py`
- `tests/test_config.py`
- `tests/test_audit_archive.py`
- `tests/test_excel_exporter.py`
- `tests/test_processor.py`
- `tests/test_scraper.py`
- `tests/test_url_security.py`
- `tests/test_word_parser.py`

目前共有 9 個測試模組、47 個測試案例。這是測試檔案與案例數，不代表覆蓋率百分比；若需要覆蓋率，應另外執行 coverage 工具產生報告。

## 已知風險與注意事項

- `services/summarizer.py` 目前沒有被主流程呼叫，可視為 unused module；若沒有明確 roadmap，應避免在架構文件中把它描述成核心流程。
- `config.py` 的 fallback 預設值可能造成缺少 `.env` 時仍啟動但連到不預期的 endpoint。
- 單一 container 內同時跑 FastAPI 與 Streamlit，部署簡單，但無法獨立擴縮兩個入口。
- 外部網站 HTML 結構不穩定，scraper 可能因網站改版、cookie wall、反自動化機制或缺少語意化日期欄位而失敗。
- Excel 單格有長度限制；目前 exporter 沒有實作顯式截斷策略。
