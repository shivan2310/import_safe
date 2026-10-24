import os

from dotenv import load_dotenv

load_dotenv()


def tinyfish_api_key() -> str | None:
    return os.getenv("TINYFISH_API_KEY") or None


def tinyfish_base_url() -> str:
    return os.getenv("TINYFISH_BASE_URL", "https://agent.tinyfish.ai").rstrip("/")


def tinyfish_timeout_s() -> float:
    return float(os.getenv("TINYFISH_TIMEOUT_S", "120"))


def allow_demo_fallback() -> bool:
    return os.getenv("ALLOW_DEMO_FALLBACK", "true").lower() in ("1", "true", "yes")
