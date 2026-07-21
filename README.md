# 週新聞彙整系統

週新聞彙整服務，提供 Streamlit 操作介面與 FastAPI API。上傳週新聞 Word 檔案後，系統會解析新聞總表與摘要、擷取來源網站資訊、使用 vLLM 產生分類標籤，最後輸出標準 14 欄 Excel。

## 功能

- 解析 Word 總表中的新聞標題、摘要與來源網址
- 擷取來源網站英文標題、發布日期與完整英文內文
- 爬蟲先使用 `requests + BeautifulSoup`，失敗或內文太短時使用 Playwright/Chromium fallback
- 根據 Word 內的中文標題與摘要，使用分類專用 vLLM 產生 1 至 3 個新聞分類標籤
- 分類成功後，以主 vLLM 在固定標籤不變的前提下對齊中文摘要；證據不足時保留原摘要
- 僅接受固定標籤池內的類別；資訊不足、回應無效或模型呼叫失敗時標記「待人工確認」
- 產出標準格式 Excel，並清楚標示需人工確認的資料
- 在畫面顯示處理總數、來源擷取失敗數、分類待人工確認數與摘要對齊數
- 提供 FastAPI 端點，供 n8n 或其他系統上傳 Word 並下載 Excel
- 成功處理後保留原始 Word、輸出 Excel 與 metadata，供管理端稽核

> `content_tran` 不再由程式截成 4,000 字元；但 Excel 單一儲存格本身最多可保存 32,767 個字元。

## 設定

複製 `.env.example` 為 `.env` 後修改：

```powershell
Copy-Item .env.example .env
```

設定讀取順序為：已存在的環境變數優先，其次自動讀取專案根目錄的 `.env`，最後才使用公開安全的 localhost 預設值。因此本機若需要呼叫遠端 vLLM，請把實際位址放在未提交的 `.env` 中。

| 變數 | 必填 | 預設值 | 說明 |
| --- | --- | --- | --- |
| `VLLM_BASE_URL` | 否 | `http://localhost:8000` | 主 vLLM OpenAI-compatible 服務位址，用於摘要對齊；分類專用位址未設定時也會使用 |
| `VLLM_MODEL` | 否 | `diffusiongemma-4-26b` | 主模型名稱，用於摘要對齊；分類專用模型未設定時也會使用 |
| `VLLM_TIMEOUT_SECONDS` | 否 | `600` | vLLM 推論逾時秒數 |
| `VLLM_TEMPERATURE` | 否 | `0` | 模型溫度；分類任務建議維持 0 |
| `VLLM_MAX_TOKENS` | 否 | `256` | 保留的主模型輸出上限設定；目前摘要對齊改用 `SUMMARY_ALIGN_MAX_TOKENS` |
| `CLASSIFY_BASE_URL` | 否 | 同 `VLLM_BASE_URL` | 分類專用模型位址；未設定時退回主模型 |
| `CLASSIFY_MODEL` | 否 | 同 `VLLM_MODEL` | 分類專用模型名稱 |
| `CLASSIFY_MAX_TOKENS` | 否 | `64` | 分類輸出最大 token 數 |
| `SUMMARY_ALIGN_MAX_TOKENS` | 否 | `384` | 依固定分類標籤對齊中文摘要的最大輸出 token 數 |
| `SCRAPE_DELAY_SECONDS` | 否 | `0.8` | 每次網站擷取後等待秒數 |
| `CLASSIFY_DELAY_SECONDS` | 否 | `3.5` | 每次 AI 分類後等待秒數 |
| `REQUEST_TIMEOUT_SECONDS` | 否 | `7` | 網站擷取逾時秒數 |
| `AUDIT_ARCHIVE_DIR` | 否 | `audit` | 成功處理後保存輸入、輸出與 metadata 的目錄 |
| `AUDIT_RETENTION_DAYS` | 否 | `30` | 新報告留存時清除超過此天數的稽核資料夾 |

## 下載使用

```powershell
git clone https://github.com/Shaun-yc/news_tool.git
cd news_tool
```

此系統需要可連線的 vLLM OpenAI-compatible API。請依環境修改 `.env` 中的 `VLLM_BASE_URL`；若使用獨立分類模型，也要設定 `CLASSIFY_BASE_URL` 與 `CLASSIFY_MODEL`。

## 分類行為

分類模型以 Word 檔中的中文標題與中文摘要作為主要依據，並使用爬蟲擷取的英文原文證據交叉驗證。為控制模型上下文，英文原文會取開頭與結尾合計最多 6,000 字元；Excel 的 `content_tran` 仍保存完整擷取內容。

- 模型必須從固定標籤池選擇 1 至 3 個標籤，並依相關性排序；理想為 2 至 3 個，單一核心主題時允許 1 個。
- 程式會移除未知標籤與重複標籤，超過 3 個時依相關性保留前 3 個。
- 每個標籤都必須能在中文標題、中文摘要或英文原文證據中找到明確依據。
- 若沒有充分依據，模型應回傳 `NONE`。
- `NONE`、沒有有效標籤、API 錯誤或逾時都會輸出「待人工確認」，不會自動補上其他分類。

## 發布日期

`pubdate` 只接受原網站提供的高可信發布欄位，例如 JSON-LD `datePublished`、`article:published_time`、`itemprop="datePublished"` 或語意明確的 `<time>`。程式不會使用 `dateModified`，也不再從整頁 HTML 猜測第一個日期；找不到可信發布日期時會留白，避免填入活動日期或頁尾日期。

## Docker 部署（建議）

建議使用 Docker 啟動，避免本機 Python 與 Playwright Chromium 版本不一致。

```powershell
# 首次啟動 / 程式碼更新後
docker compose up -d --build

# 日常啟動
docker compose up -d

# 停止
docker compose down

# 即時 log
docker compose logs -f
```

啟動後：
- Streamlit UI：`http://localhost:8501`
- FastAPI 健康檢查：`http://localhost:8001/health`

> Docker image 會安裝 Playwright Chromium，首次 build 時間較長。

成功處理的稽核檔案會保存在主機的 `./audit`（Windows 專案路徑預設為 `D:\news_tool\audit`）；每筆包含 `input.docx`、`output.xlsx` 與 `metadata.json`。

## 本機啟動（開發用）

前置條件：Python 3.12。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium

# 分別啟動兩個服務
.venv\Scripts\python.exe -m streamlit run app.py
.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8001
```

## API / n8n 串接

FastAPI 服務開在 `8001`，提供以下端點：

| Method | Path | 說明 |
| --- | --- | --- |
| `GET` | `/health` | API 健康檢查 |
| `POST` | `/process` | 上傳 `.docx`，回傳產出的 `.xlsx` |

在 n8n 可用 Webhook 接收 `.docx`，再以 HTTP Request 節點用 `multipart/form-data` 將 binary 欄位 `file` 傳至 `POST /process`。儲存庫目前未提供可直接匯入的 n8n workflow JSON。

### curl 測試

```powershell
curl.exe -X POST "http://localhost:8001/process" `
  -F "file=@D:\path\to\weekly.docx" `
  --output result.xlsx
```

API 回傳 Excel 檔案，並在 response headers 附上處理摘要：

| Header | 說明 |
| --- | --- |
| `X-News-Total-Count` | 總新聞數 |
| `X-News-Scrape-Failed-Count` | 擷取失敗數 |
| `X-News-Classification-Fallback-Count` | 分類待人工確認數（保留既有 header 名稱以維持相容性） |
| `X-News-Summary-Aligned-Count` | 依分類標籤完成摘要對齊的新聞數 |

## 測試

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

## 專案結構

```text
app.py                     Streamlit 操作介面
api.py                     FastAPI 自動化 API
start.sh                   Docker 容器進入點（同時啟動 FastAPI + Streamlit）
docker-compose.yml         Docker 統一啟動配置
Dockerfile                 容器建置定義
services/
  config.py                環境設定
  audit_archive.py         成功報告的輸入、輸出與 metadata 稽核留存
  processor.py             處理流程協調
  word_parser.py           Word 解析
  scraper.py               新聞網頁擷取
  classifier.py            vLLM 分類與固定標籤摘要對齊
  summarizer.py            獨立摘要 helper（目前主流程未使用）
  report_service.py        報告組裝
  excel_exporter.py        Excel 匯出
  url_security.py          URL 安全性驗證（SSRF 防護）
tests/                     pytest 單元測試
docs/
  architecture.md          現行架構與模組資料流
  adr/0001-news-tool-architecture.md
                            現行架構決策紀錄
```
