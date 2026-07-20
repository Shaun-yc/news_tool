# ADR-0001: news_tool 現行架構

## Status

Accepted

## Date

2026-07-08

## Context

`news_tool` 需要將週新聞 `.docx` 檔案轉成標準 Excel 報告。主要需求包含：

1. 解析 Word 檔中的中文標題、中文摘要與來源 URL。
2. 擷取來源網頁的英文標題、發布日期與完整文章內容。
3. 使用本地 vLLM 相容 API 產生 1 到 3 個氣候分類標籤。
4. 匯出 14 欄標準格式 Excel。
5. 同時支援人工互動流程與自動化流程。

系統目前有兩個入口：

- Streamlit：`app.py`
- FastAPI：`api.py`，包含 `GET /health` 與 `POST /process`

外部條件與限制：

- 分類依賴本地或內網 vLLM 相容服務。
- 來源網站可靠度不一，且可能需要瀏覽器 fallback。
- 使用者提供的 URL 必須在網路請求前驗證，避免 SSRF。
- 單一批次中個別文章失敗不應中斷整批報告產出。

## Decision

採用單一 Python codebase、單一 Docker container、分層 service module 的架構。

### 入口層

`app.py` 提供 Streamlit UI：

- 上傳 `.docx`。
- 呼叫 `parse_word_news()` 取得 `news_list`。
- 呼叫 `build_report_from_news_list()` 進行處理與匯出。
- 提供 Excel 下載。

`api.py` 提供 FastAPI：

- `GET /health` 回傳健康狀態。
- `POST /process` 接收 `.docx` upload。
- 呼叫 `build_weekly_news_report()`。
- 回傳 `.xlsx` `StreamingResponse`。

### 報表協調層

`services/report_service.py` 負責銜接 parse、process、export：

- `build_report_from_news_list()` 接收已解析的 `news_list`。
- `build_weekly_news_report()` 是 API 使用的 wrapper，先 parse Word，再呼叫 `build_report_from_news_list()`。
- `get_week_date()` 從檔名擷取報表日期。

### 處理層

`services/processor.py` 的 `process_news()` 將批次處理拆成兩個 sequential phases：

1. Scrape phase：逐筆呼叫 `scrape_article()`，填入 `en_title`、`pubdate`、`en_content`、`scrape_succeeded`。
2. Classify phase：逐筆呼叫 `classify_news()`，填入 `subcategory`、`classification_succeeded`。

這個設計讓 scrape 與 classify 的進度 callback 可以分開呈現，也讓失敗統計集中在 `ProcessingSummary`。

### 擷取層

`services/scraper.py` 採 requests-first、Playwright fallback：

- `_get_public_response()` 手動處理 redirect，最多 5 次。
- 每次 request 前都呼叫 `validate_public_url()`。
- Playwright fallback 在 `page.goto()` 後再次驗證 `page.url`。
- `_extract_article()` 依序嘗試 JSON-LD、`trafilatura`、BeautifulSoup `<p>`、meta description。
- 發布日期只取 JSON-LD `datePublished`、特定 meta tags 或語意明確的 `<time>`，不使用 `dateModified` 或頁面第一個日期猜測。

### 分類層

`services/classifier.py` 使用 vLLM 相容 `/v1/chat/completions`：

- Prompt 以中文標題與中文摘要為主，英文原文證據為補充。
- 英文證據限制為 6000 字元內。
- `normalize_tags()` 接受白名單中的 1 到 3 個標籤；單一核心主題可只保留 1 個，超過 3 個取前 3 個，沒有有效標籤、`NONE` 或無效輸出會進入人工確認狀態。
- vLLM request failure 會對該 base URL 啟動 300 秒 cooldown，避免連續失敗拖慢整批處理。

### 匯出層

`services/excel_exporter.py` 使用 `openpyxl` 產生 14 欄 Excel，並以 `BytesIO` 回傳。它會移除非法 XML 字元，但目前不實作內容截斷。

### 稽核留存層

`services/audit_archive.py` 在報告成功產出後保存原始 Word、輸出 Excel 與 metadata。Streamlit 與 FastAPI 共用相同留存邏輯；寫入失敗只記錄 log，不阻斷下載。Docker Compose 將主機 `./audit` 掛載至容器 `/app/audit`，並在新增資料時依 `AUDIT_RETENTION_DAYS` 清除過期資料夾。

### 設定層

`services/config.py` 將環境變數轉成 frozen `Settings` dataclass。分類專用模型未設定時會 fallback 到主模型設定；稽核目錄與保留天數分別由 `AUDIT_ARCHIVE_DIR`、`AUDIT_RETENTION_DAYS` 控制。程式內仍有 fallback 預設值，因此部署時應明確提供 `.env`，避免連到不預期的 endpoint。

## Consequences

### 優點

- 單一 codebase 同時支援 UI 與 API，重用相同 service layer。
- `processor.process_news()` 將 scrape 與 classify 分階段處理，方便進度顯示與錯誤統計。
- requests-first 降低一般靜態頁面的成本，Playwright fallback 保留處理 JS-heavy 頁面的能力。
- URL 驗證集中在網路存取前與 redirect 後，降低 SSRF 風險。
- vLLM cooldown 讓分類服務異常時不會反覆阻塞整批新聞。
- Excel 匯出與報表協調分離，便於測試輸出格式。
- 稽核副本讓管理端可檢查其他使用組別上傳的來源與分類結果。

### 代價

- FastAPI 與 Streamlit 在同一個 Docker container 內執行，部署簡單但不能獨立擴縮。
- scraper 仍受外部網站 HTML、cookie wall、反自動化策略與日期標記品質影響。
- `config.py` 的 fallback 預設值可能掩蓋缺少 `.env` 的部署問題。
- Excel 單格長度限制尚未有顯式截斷或保留策略。
- `services/summarizer.py` 目前未被主流程呼叫，文件與後續維護不應把它視為核心架構的一部分。
- 稽核資料包含使用者上傳內容，部署端需要依資料治理要求設定保留天數與存取權限。

## Alternatives Considered

### API-only 或 UI-only

未採用。現有使用情境需要 Streamlit 支援人工操作，也需要 FastAPI 支援自動化流程。

### Playwright-first scraping

未採用。Playwright 成本較高，對大多數可由 HTTP 取得 HTML 的頁面不必要。現行策略先用 `requests`，不足時再 fallback。

### 微服務拆分

目前未採用。分類、爬蟲、報表拆成多服務會增加部署與觀測成本；目前規模下單一 codebase 較容易維護。若未來需要獨立擴縮 API、UI、scraper 或 classifier，再重新評估。

### 分類失敗時補預設標籤

未採用。若 vLLM 沒有回傳任何有效標籤，系統會標記待人工確認，而不是用預設標籤補足。單一核心主題允許 1 個有效標籤。這避免報表出現看似確定但實際缺乏依據的分類。

## Notes

- 本 ADR 描述的是現行架構，不記錄 codebase-memory-mcp 的節點或邊數，因為該統計會隨掃描時間與排除規則改變。
- 若新增 `summarizer.py` 到正式流程，應更新本 ADR 或新增 ADR 說明其角色與資料流。
- 若實作 Excel 內容截斷策略，應明確定義截斷位置、提示文字與是否保留原始全文。
