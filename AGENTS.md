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
| `docker-compose.yml` | Docker 統一啟動配置 |
| `start.sh` | 容器進入點，同時啟動 FastAPI（port 8001）與 Streamlit（port 8501）|
| `services/config.py` | 設定讀取（環境變數 → `Settings` dataclass） |
| `services/word_parser.py` | 解析 `.docx`，萃取 `zh_title`、`content`、`source_url` |
| `services/scraper.py` | Playwright 擷取來源網頁，帶 delay 避免封鎖 |
| `services/classifier.py` | 呼叫 vLLM `/v1/chat/completions` 執行分類 |
| `services/processor.py` | 協調 scrape → classify 流程，回傳 `ProcessingSummary` |
| `services/report_service.py` | 組裝 Excel 報告（`build_report_from_news_list`） |
| `services/excel_exporter.py` | openpyxl 寫出 Excel 格式 |
| `services/url_security.py` | URL 安全性驗證，防止 SSRF |
| `tests/` | pytest 單元測試，對應每個 service 模組 |

## 環境設定

複製 `.env.example` 為 `.env` 後修改：

```
# 主模型（分類專用設定未提供時的 fallback）
VLLM_BASE_URL=http://192.168.0.92:8000     # vLLM 服務位址
VLLM_MODEL=diffusiongemma-4-26b            # 主模型名稱
VLLM_TIMEOUT_SECONDS=600                   # 請求 timeout（秒）
VLLM_TEMPERATURE=0                         # 生成溫度，0 = 確定性輸出
VLLM_MAX_TOKENS=256                        # 最大輸出 token

# 分類專用模型（未設定時退回主模型）
CLASSIFY_BASE_URL=http://192.168.0.92:8001 # 分類模型位址
CLASSIFY_MODEL=gemma-4-e4b                 # 分類模型名稱
CLASSIFY_MAX_TOKENS=64                     # 分類輸出最大 token

# 爬蟲設定
SCRAPE_DELAY_SECONDS=0.8                   # 每次擷取間隔（秒）
CLASSIFY_DELAY_SECONDS=3.5                 # 每次分類間隔（秒）
REQUEST_TIMEOUT_SECONDS=7                  # HTTP 請求 timeout（秒）
```

虛擬環境路徑：`.venv/`（Python 3.x，已安裝 requirements.txt）

## 關鍵慣例

- Python 版本：3.11+
- 套件管理：pip + `requirements.txt`（無 pyproject.toml）
- 虛擬環境：`.venv/`，使用 `.venv\Scripts\python.exe` 呼叫
- 所有設定透過環境變數注入，**禁止硬編碼** API URL 或 credentials
- `url_security.py` 提供 `validate_public_url()` 驗證，所有外部 URL 在 scrape 前必須通過
- 成功分類必須包含 2～5 個白名單標籤；少於 2 個時不得用預設標籤補位
- vLLM 回傳無效標籤、`NONE` 或呼叫失敗時標記為「待人工確認」，不中斷整體流程
- Playwright 須先安裝瀏覽器：`.venv\Scripts\python.exe -m playwright install chromium`

## 部署

- FastAPI 監聽 `0.0.0.0:8001`，Streamlit 監聽 `0.0.0.0:8501`
- Healthcheck 定義在 `Dockerfile`，interval 30s / timeout 5s / retries 3
- GitHub Remote：`https://github.com/Shaun-yc/news_tool.git`
