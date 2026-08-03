# `content_tran` 抓取與空白資料測試方案

## 目的

確保來源網址的新聞正文無論經由 requests 或 Playwright 取得，都不會把壓縮位元組或亂碼當成成功內容；若最後沒有可用正文，Excel 的 `content_tran` 必須留下人工查核訊息，不得靜默空白。

## Audit 基準案例

來源：`audit/20260731T085537.670391Z_6e27d60cb31d/output.xlsx`

使用者已將原本的亂碼內容刪除，因此目前下列儲存格為空白：

| Excel 列 | doc_id | 來源 | 基準失敗型態 |
| --- | --- | --- | --- |
| 11 | `20260731_10` | DOWNTOEARTH | 伺服器依 `Accept-Encoding: br` 回傳 Brotli；執行環境未解壓便將位元組解碼成亂碼 |
| 12 | `20260731_11` | KNNINDIA | audit 當時 requests 與 Playwright 都逾時 |
| 17 | `20260731_16` | CLEARBLUEMARKETS | 與 DOWNTOEARTH 相同的 Brotli 解碼問題 |

2026-08-03 live replay：DOWNTOEARTH、KNNINDIA、CLEARBLUEMARKETS 分別取得 3,998、1,766、3,782 字正文，Unicode replacement character (`�`) 數量均為 0。外站狀態會變動，因此此結果只作人工 smoke test 證據，不作 CI 的固定預期值。

## 自動化測試 seam

### 1. `scrape_article(session, source_url)`

可觀察行為：

- 一般 HTML 回應應產生可讀標題與正文。
- 不可解碼回應不得被視為成功新聞正文，應走瀏覽器 fallback。
- requests 不得主動宣告執行環境不支援的 Brotli 編碼。
- requests 與瀏覽器皆失敗時，必須回傳明確的人工查核訊息。

對應測試：

- `test_scrape_article_extracts_expected_fields`
- `test_scrape_article_uses_playwright_when_requests_content_is_corrupt`
- `test_scrape_article_uses_playwright_when_requests_fails`

### 2. `build_excel_report(news_list, week_date)`

可觀察行為：

- 有正文時，`content_tran` 應保留正文。
- `en_content` 為空字串、`None` 或只有空白時，`content_tran` 應輸出「來源內文為空，請手動確認來源網址。」。
- 超長正文的顯示列高固定，不因自動換行造成 Excel 開啟卡頓。

對應測試：

- `test_build_excel_report_keeps_standard_columns`
- `test_build_excel_report_marks_empty_content_tran_for_manual_review`
- `test_build_excel_report_limits_visible_height_for_full_article_text`

## 執行順序

```powershell
.venv\Scripts\python.exe -m pytest tests/test_scraper.py -v
.venv\Scripts\python.exe -m pytest tests/test_excel_exporter.py -v
.venv\Scripts\python.exe -m pytest tests/ -v
```

## 驗收條件

- 所有確定性測試通過。
- 新產生的 Excel 不存在空白 `content_tran`；抓取失敗列必須顯示人工查核訊息。
- 人工 live replay 成功時，正文不得包含大量 `�` 或控制字元，且標題應與來源新聞主題一致。
- live replay 失敗時，只記錄外站狀態與錯誤，不把外站暫時故障視為 CI regression。
