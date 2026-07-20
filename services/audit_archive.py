import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


def archive_report(
    input_bytes,
    input_filename,
    output_bytes,
    output_filename,
    summary,
    archive_dir,
    retention_days,
):
    archive_root = Path(archive_dir)
    archive_root.mkdir(parents=True, exist_ok=True)
    _remove_expired_archives(archive_root, retention_days)

    created_at = datetime.now(timezone.utc)
    input_hash = hashlib.sha256(input_bytes).hexdigest()
    audit_id = f"{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{input_hash[:12]}"
    audit_dir = archive_root / audit_id
    audit_dir.mkdir()

    (audit_dir / "input.docx").write_bytes(input_bytes)
    (audit_dir / "output.xlsx").write_bytes(output_bytes)
    metadata = {
        "audit_id": audit_id,
        "created_at": created_at.isoformat(),
        "input_filename": input_filename,
        "output_filename": output_filename,
        "input_sha256": input_hash,
        "total_count": summary.total_count,
        "scrape_failed_count": summary.scrape_failed_count,
        "classification_fallback_count": summary.classification_fallback_count,
        "summary_aligned_count": summary.summary_aligned_count,
    }
    (audit_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit_dir


def _remove_expired_archives(archive_root, retention_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for path in archive_root.iterdir():
        if not path.is_dir():
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified_at < cutoff:
            shutil.rmtree(path)
