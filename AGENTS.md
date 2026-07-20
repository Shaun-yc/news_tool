# AGENTS.md — news_tool

## 專案概覽

週新聞彙整工具。從 `.docx` 週新聞檔案自動解析中文標題、摘要與來源 URL，透過 Playwright 擷取來源網頁資訊，呼叫本地 vLLM 服務依中文標題與摘要執行分類，最後匯出標準格式 Excel。

提供兩種介面：
- **Streamlit 互動 UI** (`app.py`)：上傳 Word 檔後即時產出 Excel 下載
- **FastAPI REST API** (`api.py`)：供 n8n 等自動化平台呼叫 `/process` 端點

## 執行指令

```powershell
# ── Production（Docker）──────────────────────────────
# 首次啟動 / 程式碼更新後
docker compose up -d --build

# 日常啟動（不重新 build）
docker compose up -d

# 停止
docker compose down

# 即時 log
docker compose logs -f

# ── 本機開發（不使用 Docker）────────────────────────
# Streamlit UI
.venv\Scripts\python.exe -m streamlit run app.py

# FastAPI
.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8001

# ── 測試 ────────────────────────────────────────────
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe -m pytest tests/test_classifier.py -v
```

## 專案結構

| 路徑 | 說明 |
|---|---|
| `app.py` | Streamlit 主程式，上傳 Word → 產出 Excel |
| `api.py` | FastAPI 端點，`POST /process` 接收 .docx 回傳 .xlsx |
| `docker-compose.yml` | Docker 統一啟動配置（port 8001 + 8501，env_file: `.env`） |
| `Dockerfile` | Python 3.12-slim，安裝 playwright + chromium，CMD: `start.sh` |
| `.env.example` | 環境變數範本（vLLM 位址、分類模型、爬蟲設定） |
| `.streamlit/config.toml` | Streamlit 設定（address: 0.0.0.0, port: 8501, headless: true） |
| `start.sh` | 容器進入點，同時啟動 FastAPI（port 8001）與 Streamlit（port 8501）|
| `services/config.py` | 設定讀取（環境變數 → `Settings` dataclass） |
| `services/word_parser.py` | 解析 `.docx`，萃取 `zh_title`、`content`、`source_url` |
| `services/scraper.py` | 擷取來源網頁標題、日期與完整文章內容，必要時使用 Playwright fallback |
| `services/classifier.py` | 呼叫 vLLM `/v1/chat/completions` 執行分類（16 個氣候標籤池，1～3 個標籤，含 vLLM cooldown 機制） |
| `services/summarizer.py` | 將英文全文摘要成繁體中文（目前未被任何地方 import，為 dead code） |
| `services/processor.py` | 協調 scrape → classify 流程，回傳 `ProcessingSummary` |
| `services/report_service.py` | 組裝 Excel 報告（`build_report_from_news_list`） |
| `services/excel_exporter.py` | openpyxl 寫出 Excel 格式 |
| `services/url_security.py` | URL 安全性驗證，防止 SSRF |
| `tests/` | pytest 單元測試，對應每個 service 模組 |

## 環境設定

複製 `.env.example` 為 `.env` 後修改：

```
# 主模型（分類專用設定未提供時的 fallback）
VLLM_BASE_URL=http://localhost:8000        # vLLM 服務位址
VLLM_MODEL=diffusiongemma-4-26b            # 主模型名稱
VLLM_TIMEOUT_SECONDS=600                   # 請求 timeout（秒）
VLLM_TEMPERATURE=0                         # 生成溫度，0 = 確定性輸出
VLLM_MAX_TOKENS=256                        # 最大輸出 token

# 分類專用模型（未設定時退回主模型）
CLASSIFY_BASE_URL=http://localhost:8001    # 分類模型位址
CLASSIFY_MODEL=gemma-4-e4b                 # 分類模型名稱
CLASSIFY_MAX_TOKENS=64                     # 分類輸出最大 token

# 爬蟲設定
SCRAPE_DELAY_SECONDS=0.8                   # 每次擷取間隔（秒）
CLASSIFY_DELAY_SECONDS=3.5                 # 每次分類間隔（秒）
REQUEST_TIMEOUT_SECONDS=7                  # HTTP 請求 timeout（秒）
```

設定讀取順序為：已存在的環境變數優先，其次自動讀取專案根目錄的 `.env`，最後才使用公開安全的 localhost 預設值。實際內網或私有 vLLM 位址應放在未提交的 `.env` 中。

虛擬環境路徑：`.venv/`（Python 3.x，已安裝 requirements.txt）

## 關鍵慣例

- Python 版本：3.11+
- 套件管理：pip + `requirements.txt`（無 pyproject.toml）
- 虛擬環境：`.venv/`，使用 `.venv\Scripts\python.exe` 呼叫
- 所有設定透過環境變數或未提交的 `.env` 注入，**原則上禁止硬編碼** API URL 或 credentials；但 `services/config.py` 對 `VLLM_BASE_URL`、`VLLM_MODEL`、`CLASSIFY_BASE_URL`、`CLASSIFY_MODEL` 有 fallback 預設值（從 `.env.example` 而來），若無 `.env` 時會使用這些預設
- `url_security.py` 提供 `validate_public_url()` 驗證，所有外部 URL 在 scrape 前必須通過
- `en_content` 必須保留擷取到的完整文章，不得在 scraper 任意截斷；Excel 單格仍受 32,767 字元上限約束
- `pubdate` 只能來自高可信發布欄位；不得以整頁第一個日期或 `dateModified` 猜測，缺少可信日期時留白
- 成功分類必須包含 1～3 個白名單標籤；理想為 2～3 個，單一核心主題時允許 1 個，且不得用預設標籤補位
- 分類以中文標題與摘要為主，英文原文證據為輔；爬取失敗訊息不得送入分類 Prompt
- vLLM 回傳無效標籤、`NONE` 或呼叫失敗時標記為「待人工確認」，不中斷整體流程
- Playwright 須先安裝瀏覽器：`.venv\Scripts\python.exe -m playwright install chromium`

## 資料流

```
[上傳 .docx]
    ↓
app.py / api.py
    ↓
report_service.build_report_from_news_report / build_weekly_news_report
    ↓ (先 parse)
word_parser.parse_word_news → news_list [{zh_title, content, source_url}]
    ↓ (再 process)
processor.process_news
    ├── Phase 1: scraper.scrape_article → 填入 {en_title, pubdate, en_content, scrape_succeeded}
    │       ├─ validate_public_url (SSRF 防護)
    │       ├─ _scrape_with_requests (優先，follow redirects up to 5x)
    │       │   └─ _extract_article: JSON-LD → trafilatura → BS4 <p> → meta description
    │       └─ _scrape_with_playwright (fallback，含 cookie 彈窗處理、stealth script)
    │
    └─ Phase 2: classifier.classify_news → 填入 {subcategory, classification_succeeded}
            ├─ _build_prompt (中文標題 + 摘要 + 英文證據，上限 6000 chars)
            ├─ _classify_with_vllm (POST /v1/chat/completions)
            ├─ normalize_tags (清洗輸出 → 1～3 個白名單標籤)
            └─ vLLM cooldown 機制（連續失敗後 300 秒內不重試）
    ↓
excel_exporter.build_excel_report → openpyxl BytesIO (14 欄標準格式)
```

## 部署

- FastAPI 監聽 `0.0.0.0:8001`，Streamlit 監聽 `0.0.0.0:8501`
- Healthcheck 定義在 `Dockerfile`，interval 30s / timeout 5s / retries 3
- GitHub Remote：`https://github.com/Shaun-yc/news_tool.git`
