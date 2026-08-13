import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.audit_archive import archive_report, archive_report_safely
from services.processor import ProcessingSummary


class AuditArchiveTests(unittest.TestCase):
    def test_archive_report_safely_returns_archive_path(self):
        expected_path = Path("audit-id")

        def archive_fn(*args):
            return expected_path

        result = archive_report_safely(
            archive_fn,
            b"docx",
            "input.docx",
            b"xlsx",
            "output.xlsx",
            ProcessingSummary(1, 0, 0, 0),
            "audit",
            30,
        )

        self.assertEqual(result, expected_path)

    def test_archive_report_safely_propagates_unexpected_errors(self):
        def archive_fn(*args):
            raise RuntimeError("unexpected")

        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            archive_report_safely(
                archive_fn,
                b"docx",
                "input.docx",
                b"xlsx",
                "output.xlsx",
                ProcessingSummary(1, 0, 0, 0),
                "audit",
                30,
            )

    def test_archive_report_saves_input_output_and_metadata(self):
        summary = ProcessingSummary(
            total_count=3,
            scrape_failed_count=1,
            classification_fallback_count=2,
            summary_aligned_count=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            audit_dir = archive_report(
                b"docx-bytes",
                "週新聞_2026.07.20.docx",
                b"excel-bytes",
                "永智週新聞csv_20260720.xlsx",
                summary,
                temp_dir,
                30,
            )

            self.assertEqual((audit_dir / "input.docx").read_bytes(), b"docx-bytes")
            self.assertEqual((audit_dir / "output.xlsx").read_bytes(), b"excel-bytes")
            metadata = json.loads((audit_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["input_filename"], "週新聞_2026.07.20.docx")
            self.assertEqual(metadata["total_count"], 3)
            self.assertEqual(metadata["classification_fallback_count"], 2)

    def test_archive_report_removes_expired_directories_only(self):
        summary = ProcessingSummary(1, 0, 0, 0)
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_root = Path(temp_dir)
            expired_dir = archive_root / "20260701T000000.000000Z_0123456789ab"
            expired_dir.mkdir()
            unrelated_file = archive_root / "keep.txt"
            unrelated_file.write_text("keep", encoding="utf-8")
            expired_time = (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
            os.utime(expired_dir, (expired_time, expired_time))

            archive_report(
                b"docx",
                "input.docx",
                b"xlsx",
                "output.xlsx",
                summary,
                archive_root,
                30,
            )

            self.assertFalse(expired_dir.exists())
            self.assertTrue(unrelated_file.exists())


if __name__ == "__main__":
    unittest.main()
