import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    vllm_base_url: str
    vllm_model: str
    vllm_temperature: float
    vllm_max_tokens: int
    scrape_delay_seconds: float
    classify_delay_seconds: float
    request_timeout_seconds: float
    vllm_timeout_seconds: float
    # 分類專用模型（獨立 port）；未設定時退回主模型
    classify_base_url: str
    classify_model: str
    classify_max_tokens: int
    summary_align_max_tokens: int


def _get_float(name, default, minimum=0):
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        return default
    return value if value >= minimum else default


def _get_int(name, default, minimum=0):
    try:
        value = int(os.getenv(name, default))
    except ValueError:
        return default
    return value if value >= minimum else default


def _load_env_file(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("\"'"))


def get_settings(env_file=".env"):
    if env_file:
        _load_env_file(env_file)

    main_url = os.getenv("VLLM_BASE_URL") or "http://localhost:8000"
    main_model = os.getenv("VLLM_MODEL") or "diffusiongemma-4-26b"
    return Settings(
        vllm_base_url=main_url,
        vllm_model=main_model,
        vllm_temperature=_get_float("VLLM_TEMPERATURE", 0.0),
        vllm_max_tokens=_get_int("VLLM_MAX_TOKENS", 256, minimum=16),
        scrape_delay_seconds=_get_float("SCRAPE_DELAY_SECONDS", 0.8),
        classify_delay_seconds=_get_float("CLASSIFY_DELAY_SECONDS", 3.5),
        request_timeout_seconds=_get_float("REQUEST_TIMEOUT_SECONDS", 7.0, minimum=0.1),
        vllm_timeout_seconds=_get_float("VLLM_TIMEOUT_SECONDS", 600.0, minimum=0.1),
        classify_base_url=os.getenv("CLASSIFY_BASE_URL") or main_url,
        classify_model=os.getenv("CLASSIFY_MODEL") or main_model,
        classify_max_tokens=_get_int("CLASSIFY_MAX_TOKENS", 64, minimum=16),
        summary_align_max_tokens=_get_int("SUMMARY_ALIGN_MAX_TOKENS", 384, minimum=64),
    )
