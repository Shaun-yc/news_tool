# CLAUDE.md — news_tool

## 專案概覽

週新聞彙整工具。從 `.docx` 週新聞檔案自動解析標題與來源 URL，透過 Playwright 擷取來源網頁全文，呼叫本地 vLLM 服務執行分類，最後匯出標準格式 Excel。

提供兩種介面：
- **Streamlit 互動 UI** (`app.py`)：上傳 Word 檔後即時產出 Excel 下載
- **FastAPI REST API** (`api.py`)：供 n8n 等自動化平台呼叫 `/process` 端點

## 執行指令

```powershell
# 啟動 Streamlit UI（開發用）
cd D:\news_tool
.venv\Scripts\python.exe -m streamlit run app.py

# 啟動 FastAPI（n8n 整合）
.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8502

# 執行測試
.venv\Scripts\python.exe -m pytest tests/ -v

# 執行單一測試
.venv\Scripts\python.exe -m pytest tests/test_classifier.py -v

# Docker 啟動（完整 Production）
docker build -t news_tool .
docker run --env-file .env -p 8501:8501 news_tool
```

## 專案結構

| 路徑 | 說明 |
|---|---|
| `app.py` | Streamlit 主程式，上傳 Word → 產出 Excel |
| `api.py` | FastAPI 端點，`POST /process` 接收 .docx 回傳 .xlsx |
| `services/config.py` | 設定讀取（環境變數 → `Settings` dataclass） |
| `services/word_parser.py` | 解析 `.docx`，萃取 `zh_title`、`en_title`、`url` |
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
VLLM_BASE_URL=http://192.168.0.92:8000     # 本地 vLLM 服務位址
VLLM_MODEL=diffusiongemma-4-26b            # 使用的模型名稱
VLLM_TIMEOUT_SECONDS=600                   # vLLM 請求 timeout（秒）
VLLM_TEMPERATURE=0                         # 生成溫度，0 = 確定性輸出
VLLM_MAX_TOKENS=256                        # 分類輸出最大 token 數
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
- `url_security.py` 提供 `is_safe_url()` 驗證，所有外部 URL 在 scrape 前必須通過
- vLLM 呼叫失敗時 fallback 預設分類標籤，不中斷整體流程
- Playwright 須先安裝瀏覽器：`.venv\Scripts\python.exe -m playwright install chromium`

## 部署

- Streamlit 預設監聽 `0.0.0.0:8501`（見 `.streamlit/config.toml`）
- FastAPI 建議以 `0.0.0.0:8502` 啟動，避免與 Streamlit 衝突
- GitHub Remote：`https://github.com/Shaun-yc/news_tool.git`
