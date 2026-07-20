import io
import logging
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from services.audit_archive import archive_report
from services.config import get_settings
from services.report_service import build_weekly_news_report


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Weekly News Tool API", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process")
def process_weekly_news(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="請上傳 .docx 週新聞檔案")

    try:
        settings = get_settings()
        input_bytes = file.file.read()
        report, output_filename, summary = build_weekly_news_report(
            io.BytesIO(input_bytes),
            file.filename,
            settings,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Weekly news API processing failed")
        raise HTTPException(status_code=500, detail="處理失敗，請查看服務日誌") from error

    output_bytes = report.getvalue()
    try:
        audit_dir = archive_report(
            input_bytes,
            file.filename,
            output_bytes,
            output_filename,
            summary,
            settings.audit_archive_dir,
            settings.audit_retention_days,
        )
        logger.info("Audit files saved to %s", audit_dir)
    except OSError:
        logger.exception("Failed to save audit files")

    headers = {
        "Content-Disposition": (
            f"attachment; filename=weekly-news.xlsx; filename*=UTF-8''{quote(output_filename)}"
        ),
        "X-News-Total-Count": str(summary.total_count),
        "X-News-Scrape-Failed-Count": str(summary.scrape_failed_count),
        "X-News-Classification-Fallback-Count": str(summary.classification_fallback_count),
        "X-News-Summary-Aligned-Count": str(summary.summary_aligned_count),
    }
    return StreamingResponse(
        io.BytesIO(output_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
