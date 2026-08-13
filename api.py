import io
import logging
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, is_zipfile
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
        if is_zipfile(io.BytesIO(input_bytes)):
            with ZipFile(io.BytesIO(input_bytes)) as package:
                required_members = {
                    "[Content_Types].xml",
                    "_rels/.rels",
                    "word/document.xml",
                }
                if not required_members.issubset(package.namelist()):
                    raise ValueError("請上傳有效的 .docx 週新聞檔案")
                try:
                    content_types_root = ElementTree.fromstring(
                        package.read("[Content_Types].xml")
                    )
                    relationships_root = ElementTree.fromstring(package.read("_rels/.rels"))
                    document_root = ElementTree.fromstring(package.read("word/document.xml"))
                except (ElementTree.ParseError, LookupError) as error:
                    raise ValueError("請上傳有效的 .docx 週新聞檔案") from error

                content_types_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
                document_content_type = (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                )
                has_document_content_type = any(
                    child.tag == f"{{{content_types_namespace}}}Override"
                    and child.attrib.get("PartName") == "/word/document.xml"
                    and child.attrib.get("ContentType") == document_content_type
                    for child in content_types_root
                )

                relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
                office_document_relationship = (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
                )
                has_document_relationship = any(
                    child.tag == f"{{{relationships_namespace}}}Relationship"
                    and child.attrib.get("Type") == office_document_relationship
                    and child.attrib.get("Target") in {"word/document.xml", "/word/document.xml"}
                    for child in relationships_root
                )

                if (
                    content_types_root.tag != f"{{{content_types_namespace}}}Types"
                    or not has_document_content_type
                    or relationships_root.tag != f"{{{relationships_namespace}}}Relationships"
                    or not has_document_relationship
                    or document_root.tag
                    != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document"
                ):
                    raise ValueError("請上傳有效的 .docx 週新聞檔案")
        report, output_filename, summary = build_weekly_news_report(
            io.BytesIO(input_bytes),
            file.filename,
            settings,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except BadZipFile as error:
        raise HTTPException(
            status_code=400,
            detail="請上傳有效的 .docx 週新聞檔案",
        ) from error
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
