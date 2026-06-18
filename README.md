# 週新聞彙整系統

正式版 Streamlit 服務。上傳週新聞 Word 檔案後，系統會解析新聞總表與摘要、擷取來源網站資訊、使用 vLLM 產生分類標籤，最後輸出標準 14 欄 Excel。

## 功能

- 解析 Word 總表中的新聞標題、摘要與來源網址
- 擷取來源網站英文標題、發布日期與英文內文
- 爬蟲先使用 `requests + BeautifulSoup`，失敗或內文太短時使用 Playwright/Chromium fallback
- 使用內網 vLLM 產生 2 至 5 個新聞分類標籤
- 產出標準格式 Excel，並標示需人工確認的資料
- 在畫面顯示處理總數、來源擷取失敗數與分類 fallback 數
- 提供 FastAPI 端點，供 n8n 或其他系統上傳 Word 並下載 Excel

## 設定

以環境變數設定服務。可參考 `.env.example`。此檔案是部署設定範本，程式不會自動載入：

| 變數 | 必填 | 預設值 | 說明 |
| --- | --- | --- | --- |
| `VLLM_BASE_URL` | 否 | `http://192.168.0.92:8000` | vLLM OpenAI-compatible 服務位址 |
| `VLLM_MODEL` | 否 | `diffusiongemma-4-26b` | vLLM 分類模型 |
| `VLLM_TIMEOUT_SECONDS` | 否 | `600` | vLLM 推論逾時秒數；首次載入大型模型可能較久 |
| `VLLM_TEMPERATURE` | 否 | `0` | 模型溫度；分類任務建議維持 0，降低幻想標籤機率 |
| `VLLM_MAX_TOKENS` | 否 | `256` | 最大輸出 token 數；分類標籤通常不需要太大 |
| `SCRAPE_DELAY_SECONDS` | 否 | `0.8` | 每次網站擷取後等待秒數 |
| `CLASSIFY_DELAY_SECONDS` | 否 | `3.5` | 每次 AI 分類後等待秒數 |
| `REQUEST_TIMEOUT_SECONDS` | 否 | `7` | 網站擷取逾時秒數 |

## 下載使用

從 GitHub 下載專案：

```powershell
git clone https://github.com/Shaun-yc/news_tool.git
cd news_tool
```

此系統需要可連線的 vLLM OpenAI-compatible API。預設範例使用內網位址 `http://192.168.0.92:8000`，若部署在其他環境，請將 `VLLM_BASE_URL` 改成自己的 vLLM 服務位址。

## 本機啟動

前置條件：Windows 已安裝 Python 3.12。先確認版本：

```powershell
python --version
```

若系統找不到 `python`，可使用 `winget` 安裝後重新開啟 PowerShell：

```powershell
winget install --exact --id Python.Python.3.12
```

在專案目錄執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

開啟 `http://localhost:8501`。

若 `.venv` 是使用其他 Python 安裝建立，或原 Python 已移除，請先刪除舊的 `.venv` 再重新建立。

## Docker 部署

建議使用 Docker 啟動，避免本機 Python 與 Playwright Chromium 版本不一致：

```powershell
docker build -t weekly-news-tool .
docker run --rm -p 8501:8501 -p 8001:8001 `
  -e VLLM_BASE_URL="http://192.168.0.92:8000" `
  -e VLLM_MODEL="diffusiongemma-4-26b" `
  -e VLLM_TEMPERATURE="0" `
  -e VLLM_MAX_TOKENS="256" `
  weekly-news-tool
```

Docker image 會安裝 Playwright Chromium，因此首次 build 會比純 Python image 久。

健康檢查端點：

- Streamlit：`http://localhost:8501/_stcore/health`
- FastAPI：`http://localhost:8001/health`

啟動後開啟：`http://localhost:8501`

## n8n 串接

FastAPI 服務預設開在 `8001`，提供以下端點：

| Method | Path | 說明 |
| --- | --- | --- |
| `GET` | `/health` | API 健康檢查 |
| `POST` | `/process` | 上傳 `.docx`，回傳產出的 `.xlsx` |

n8n 使用 `HTTP Request` node：

| 設定 | 值 |
| --- | --- |
| Method | `POST` |
| URL | `http://<news-tool-host>:8001/process` |
| Body Content Type | `Form-Data` |
| Form field name | `file` |
| Form field type | Binary/File |
| Response Format | File |

API 回傳 Excel 檔案，並在 response headers 附上處理摘要：

- `X-News-Total-Count`
- `X-News-Scrape-Failed-Count`
- `X-News-Classification-Fallback-Count`

curl 測試：

```powershell
curl.exe -X POST "http://localhost:8001/process" `
  -F "file=@D:\path\to\週新聞_2026.06.18.docx" `
  -o "永智週新聞csv_20260618.xlsx"
```

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 專案結構

```text
app.py                     Streamlit 操作介面
api.py                     FastAPI 自動化 API
services/config.py         環境設定
services/processor.py      處理流程
services/word_parser.py    Word 解析
services/scraper.py        新聞網頁擷取
services/classifier.py     vLLM 分類
services/excel_exporter.py Excel 匯出
tests/                     本機單元測試
```
