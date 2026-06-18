import os
import unittest
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
            settings = get_settings()

        self.assertEqual(settings.vllm_base_url, "http://192.168.0.92:8000")
        self.assertEqual(settings.vllm_model, "diffusiongemma-4-26b")
        self.assertEqual(settings.vllm_temperature, 0.0)
        self.assertEqual(settings.vllm_max_tokens, 256)
        self.assertEqual(settings.scrape_delay_seconds, 0.8)
        self.assertEqual(settings.classify_delay_seconds, 3.5)
        self.assertEqual(settings.request_timeout_seconds, 7.0)
        self.assertEqual(settings.vllm_timeout_seconds, 600.0)


if __name__ == "__main__":
    unittest.main()
