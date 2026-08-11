import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings:
    def __init__(self) -> None:
        self.db_path = Path(os.getenv("HOME_FLOW_DB_PATH", ROOT_DIR / "data" / "storage" / "home_flow.db"))
        self.image_root = Path(os.getenv("HOME_FLOW_IMAGE_ROOT", ROOT_DIR / "data" / "incoming"))
        self.default_city = os.getenv("HOME_FLOW_DEFAULT_CITY", "\u5b81\u6ce2\u5e02")
        self.ocr_auto_confirm_threshold = float(os.getenv("HOME_FLOW_OCR_AUTO_CONFIRM_THRESHOLD", "0.92"))
        self.llm_enabled = os.getenv("HOME_FLOW_LLM_ENABLED", "false").lower() == "true"
        self.llm_provider = os.getenv("HOME_FLOW_LLM_PROVIDER", "deepseek")
        self.llm_api_key = os.getenv("HOME_FLOW_LLM_API_KEY", "")
        self.llm_base_url = os.getenv("HOME_FLOW_LLM_BASE_URL", "https://api.deepseek.com")
        self.llm_model = os.getenv("HOME_FLOW_LLM_MODEL", "deepseek-chat")
        self.llm_timeout_seconds = float(os.getenv("HOME_FLOW_LLM_TIMEOUT_SECONDS", "30"))


settings = Settings()
