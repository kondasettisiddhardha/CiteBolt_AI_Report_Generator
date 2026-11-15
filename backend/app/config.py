"""Application configuration.

Every setting comes from the environment (loaded from backend/.env when it
exists). `env.example` shows the expected shape.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_CANDIDATES = [BASE_DIR.parent / ".env", BASE_DIR / ".env"]
ENV_FILE = next((path for path in ENV_CANDIDATES if path.is_file()), ENV_CANDIDATES[0])

try:
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE, override=False)
except ImportError:  # pragma: no cover - dotenv is in requirements.txt
    pass


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- Research pipeline -------------------------------------------------
TARGET_SOURCE_COUNT = 5
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 2

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
_fallback_raw = os.getenv("GROQ_FALLBACK_MODELS", "")
GROQ_FALLBACK_MODELS: list[str] = [
    m.strip() for m in _fallback_raw.split(",") if m.strip()
]
if not GROQ_FALLBACK_MODELS:
    GROQ_FALLBACK_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# --- Model Pricing (USD per 1M tokens) ---------------------------------
MODEL_PRICING: dict[str, dict[str, float]] = {
    "openai/gpt-oss-120b": {"input_per_million": 0.15, "output_per_million": 0.60},
    "qwen/qwen3.8-27b": {"input_per_million": 0.20, "output_per_million": 0.60},
    "openai/gpt-oss-20b": {"input_per_million": 0.08, "output_per_million": 0.24},
    "llama-3.3-70b-versatile": {"input_per_million": 0.59, "output_per_million": 0.79},
    "llama-3.1-70b-versatile": {"input_per_million": 0.59, "output_per_million": 0.79},
    "llama-3.1-8b-instant": {"input_per_million": 0.05, "output_per_million": 0.08},
    "mixtral-8x7b-32768": {"input_per_million": 0.24, "output_per_million": 0.24},
    "default": {"input_per_million": 0.20, "output_per_million": 0.50},
}

# --- Server ------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = _read_int("PORT", 8000)
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
)
RUN_TTL_SECONDS = _read_int("RUN_TTL_SECONDS", 3600)
RETRIES = _read_int("RETRIES", DEFAULT_RETRIES)
BACKOFF = _read_int("BACKOFF", DEFAULT_BACKOFF)

# --- Database ----------------------------------------------------------
# SQLite by default; set DATABASE_URL to a Postgres URL to switch drivers.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- Auth --------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
SESSION_COOKIE = "citebolt_session"
SESSION_DAYS = _read_int("SESSION_DAYS", 7)
OTP_TTL_SECONDS = _read_int("OTP_TTL_SECONDS", 600)
OTP_MAX_ATTEMPTS = _read_int("OTP_MAX_ATTEMPTS", 5)
OTP_MAX_REQUESTS = _read_int("OTP_MAX_REQUESTS", 3)
OTP_REQUEST_WINDOW_SECONDS = _read_int("OTP_REQUEST_WINDOW_SECONDS", 600)
OTP_RESEND_SECONDS = _read_int("OTP_RESEND_SECONDS", 30)

# --- Email -------------------------------------------------------------
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "CiteBolt <onboarding@resend.dev>")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _read_int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", CONTACT_EMAIL or "")
APP_NAME = os.getenv("APP_NAME", "CiteBolt")

# --- Limits ------------------------------------------------------------
DAILY_RUN_LIMIT = _read_int("DAILY_RUN_LIMIT", 10)
MAX_TOPIC_CHARS = _read_int("MAX_TOPIC_CHARS", 300)
MAX_CONTEXT_CHARS = _read_int("MAX_CONTEXT_CHARS", 40000)
MAX_UPLOAD_BYTES = _read_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)

# --- Frontend ----------------------------------------------------------
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
