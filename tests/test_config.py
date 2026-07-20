import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.config import get_settings


class ConfigTests(unittest.TestCase):
    def test_get_settings_uses_defaults_for_invalid_optional_values(self):
        with patch.dict(
            os.environ,
            {
                "SCRAPE_DELAY_SECONDS": "-1",
                "CLASSIFY_DELAY_SECONDS": "invalid",
                "REQUEST_TIMEOUT_SECONDS": "0",
                "VLLM_TIMEOUT_SECONDS": "0",
                "VLLM_TEMPERATURE": "invalid",
                "VLLM_MAX_TOKENS": "0",
            },
            clear=True,
        ):
            settings = get_settings(env_file=None)

        self.assertEqual(settings.vllm_base_url, "http://localhost:8000")
        self.assertEqual(settings.vllm_model, "diffusiongemma-4-26b")
        self.assertEqual(settings.vllm_temperature, 0.0)
        self.assertEqual(settings.vllm_max_tokens, 256)
        self.assertEqual(settings.summary_align_max_tokens, 384)
        self.assertEqual(settings.scrape_delay_seconds, 0.8)
        self.assertEqual(settings.classify_delay_seconds, 3.5)
        self.assertEqual(settings.request_timeout_seconds, 7.0)
        self.assertEqual(settings.vllm_timeout_seconds, 600.0)
        self.assertEqual(settings.audit_archive_dir, "audit")
        self.assertEqual(settings.audit_retention_days, 30)

    def test_get_settings_loads_local_env_without_overriding_process_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "VLLM_BASE_URL=http://192.168.0.92:8000",
                        "CLASSIFY_BASE_URL=http://192.168.0.92:8001",
                        "VLLM_MODEL=local-main",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"VLLM_BASE_URL": "http://configured-host:9000"},
                clear=True,
            ):
                settings = get_settings(env_file=env_file)

        self.assertEqual(settings.vllm_base_url, "http://configured-host:9000")
        self.assertEqual(settings.classify_base_url, "http://192.168.0.92:8001")
        self.assertEqual(settings.vllm_model, "local-main")


if __name__ == "__main__":
    unittest.main()
