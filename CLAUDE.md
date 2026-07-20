# CLAUDE.md — news_tool

## 專案概覽

週新聞彙整工具。從 `.docx` 解析中文標題、摘要與來源 URL，以 requests-first／Playwright fallback 擷取來源網頁，再呼叫 vLLM 進行氣候標籤分類與來源證據支持的中文摘要對齊，最後輸出 14 欄 Excel。

入口有兩個：

- `app.py`：Streamlit UI，上傳 Word 後下載 Excel。
- `api.py`：FastAPI，提供 `GET /health` 與 `POST /process`。

## 執行指令

```powershell
# Docker production
docker compose up -d --build
docker compose up -d
docker compose down
docker compose logs -f

# 本機開發
.venv\Scripts\python.exe -m streamlit run app.py
.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8001

# 測試
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe -m pytest tests/test_classifier.py -v
```

## 專案結構

| 路徑 | 說明 |
| --- | --- |
| `app.py` | Streamlit 上傳、進度、稽核留存與下載介面 |
| `api.py` | FastAPI 健康檢查與 `.docx` → `.xlsx` API |
| `services/config.py` | `.env`／環境變數 → frozen `Settings` |
| `services/word_parser.py` | 解析 `.docx` 為 `zh_title`、`content`、`source_url` |
| `services/url_security.py` | 公開 URL 驗證與 SSRF 防護 |
| `services/scraper.py` | requests-first 擷取；Playwright fallback；保留完整文章 |
| `services/classifier.py` | 白名單標籤分類、vLLM cooldown、固定標籤摘要對齊 |
| `services/processor.py` | scrape → classify → summary alignment 協調與統計 |
| `services/report_service.py` | parse／process／export 報表流程封裝 |
| `services/excel_exporter.py` | openpyxl 產生 14 欄 Excel `BytesIO` |
| `services/audit_archive.py` | 保存成功報告的輸入、輸出、metadata 並清理逾期資料 |
| `services/summarizer.py` | 未被主流程 import 的舊摘要 helper |
| `tests/` | 9 個 pytest 模組，覆蓋 API 與各 service |
| `docs/architecture.md` | 現行架構、資料流與模組責任 |
| `docs/adr/0001-news-tool-architecture.md` | 現行架構決策紀錄 |
| `Dockerfile` | Python 3.12-slim + Playwright Chromium；FastAPI healthcheck |
| `docker-compose.yml` | ports 8001/8501、`.env`、`./audit:/app/audit` |
| `start.sh` | 同一容器啟動 FastAPI 與 Streamlit |

## 環境設定

先複製 `.env.example` 為未提交的 `.env`。既有 process environment 優先，其次載入 `.env` 中尚未存在的鍵，最後才用 `services/config.py` 的 fallback。

```text
VLLM_BASE_URL=http://localhost:8000
VLLM_MODEL=diffusiongemma-4-26b
VLLM_TIMEOUT_SECONDS=600
VLLM_TEMPERATURE=0
VLLM_MAX_TOKENS=256

CLASSIFY_BASE_URL=http://localhost:8001
CLASSIFY_MODEL=gemma-4-e4b
CLASSIFY_MAX_TOKENS=64
SUMMARY_ALIGN_MAX_TOKENS=384

SCRAPE_DELAY_SECONDS=0.8
CLASSIFY_DELAY_SECONDS=3.5
REQUEST_TIMEOUT_SECONDS=7

AUDIT_ARCHIVE_DIR=audit
AUDIT_RETENTION_DAYS=30
```

主模型用於分類成功後的摘要對齊；分類專用設定缺少時退回主模型。`VLLM_MAX_TOKENS` 目前未進入主流程的模型呼叫，摘要對齊使用 `SUMMARY_ALIGN_MAX_TOKENS`。

## 關鍵慣例

- Python 3.11+；Docker 使用 Python 3.12。
- 使用 pip + `requirements.txt`，無 `pyproject.toml`。
- 所有外部 URL 在 requests、redirect 與 Playwright 最終頁面存取前必須經過 `validate_public_url()`。
- `en_content` 保留 scraper 擷取的全文；exporter 不主動截斷，但 Excel 單格上限仍為 32,767 字元。
- `pubdate` 只接受可信發布欄位，不以 `dateModified` 或頁面任意日期猜測。
- 分類依中文標題與摘要為主、英文來源證據為輔；只接受 16 個白名單中的 1～3 個標籤。
- `NONE`、無效標籤、模型錯誤或 cooldown 一律輸出「待人工確認」，不補預設標籤。
- 只有分類成功才嘗試摘要對齊；標籤固定不變，證據不足、輸出不合規或模型錯誤時保留原摘要。
- 擷取失敗訊息不得放入分類或摘要對齊 prompt。
- Playwright 瀏覽器需先安裝：`.venv\Scripts\python.exe -m playwright install chromium`。

## 資料流

```text
.docx
  -> app.py: parse_word_news() / api.py: build_weekly_news_report()
  -> report_service.build_report_from_news_list()
  -> processor.process_news()
       1. scraper.scrape_article()
       2. classifier.classify_news()
       3. classifier.align_summary_to_tags()（僅分類成功）
  -> excel_exporter.build_excel_report()
  -> audit_archive.archive_report()
  -> Streamlit download / FastAPI StreamingResponse
```

`ProcessingSummary` 包含 `total_count`、`scrape_failed_count`、`classification_fallback_count`、`summary_aligned_count`；API 以四個 `X-News-*` headers 回傳相同統計。

## 部署

- FastAPI：`0.0.0.0:8001`；Streamlit：`0.0.0.0:8501`。
- Docker healthcheck：`GET http://127.0.0.1:8001/health`，interval 30s、timeout 5s、start period 10s、retries 3。
- Docker 將 `./audit` 掛載為 `/app/audit`，避免容器重建時遺失稽核檔。
