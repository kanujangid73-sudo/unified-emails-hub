"""Application settings, read from environment variables (and an optional .env file)."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _database_url(url: str) -> str:
    """Use the psycopg 3 driver for Postgres URLs, as given by Neon, Supabase or Render."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def _origin(value: str) -> str:
    """Normalize an origin: add https:// when the scheme is missing and drop any trailing slash."""
    value = value.strip().rstrip("/")
    return value if "://" in value else f"https://{value}"


class Settings:
    app_name = "Unified Emails Hub API"
    version = "0.3.0"

    # "production" turns on the checks in check() and stops allowing localhost origins.
    environment = os.getenv("APP_ENV", "development").strip().lower()
    is_production = environment == "production"

    # SQLite by default; set a Postgres URL (e.g. from Neon) for a persistent hosted database.
    database_url = _database_url(os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'mailhub.db'}"))

    # A random key is generated when none is configured, so tokens reset on restart.
    # SECRET_KEY is required in production.
    secret_key = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
    token_expire_minutes = int(os.getenv("TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))

    # Comma-separated list of allowed frontend origins. In development, any localhost port is also allowed.
    cors_origins = [_origin(o) for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

    # One-click demo accounts: how long they last, and how many each IP address may create per hour.
    guest_ttl_hours = int(os.getenv("GUEST_TTL_HOURS", "24"))
    demo_logins_per_hour = int(os.getenv("DEMO_LOGINS_PER_HOUR", "10"))

    # Threads returned per page of the inbox.
    page_size = int(os.getenv("PAGE_SIZE", "50"))

    # Where this API and the web app are reachable; used to build OAuth redirect URLs.
    # On Render, RENDER_EXTERNAL_URL is the service's own public address.
    public_api_url = _origin(os.getenv("PUBLIC_API_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000")
    frontend_url = _origin(os.getenv("FRONTEND_URL", "http://localhost:5173"))

    # Keys that encrypt stored mailbox credentials (Fernet keys, comma-separated). The first
    # encrypts; all of them decrypt, so a key can be rotated without reconnecting accounts.
    # Without one, a key is derived from SECRET_KEY (development only).
    encryption_keys = [k.strip() for k in os.getenv("ENCRYPTION_KEY", "").split(",") if k.strip()]

    # OAuth apps. A provider is offered only when its client id and secret are set.
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    microsoft_client_id = os.getenv("MICROSOFT_CLIENT_ID", "")
    microsoft_client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    # "common" accepts both personal (outlook.com, hotmail.com) and work or school accounts.
    microsoft_tenant = os.getenv("MICROSOFT_TENANT", "common")

    # Background sync: how often each account is synced, and how far back the first sync reaches.
    sync_scheduler = _bool("SYNC_SCHEDULER", True)
    sync_interval_seconds = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
    sync_backfill_days = int(os.getenv("SYNC_BACKFILL_DAYS", "30"))
    # IMAP/SMTP servers on private networks are refused in production (see net.py).
    allow_private_hosts = _bool("ALLOW_PRIVATE_HOSTS", not is_production)

    # Emails each user may send per hour. 0 disables the limit.
    sends_per_hour = int(os.getenv("SENDS_PER_HOUR", "30"))

    # AI summaries and reply drafts, on request only. Google Gemini has a free tier; without a
    # key the server falls back to simple built-in summaries and reply templates.
    # Free-tier prompts may be used by Google to improve its products.
    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    gemini_url = os.getenv("GEMINI_URL", "https://generativelanguage.googleapis.com").rstrip("/")
    ai_enabled = _bool("AI_ENABLED", True) and bool(gemini_api_key)
    # AI requests each user may make per hour, to protect the free-tier quota. 0 = unlimited.
    ai_requests_per_hour = int(os.getenv("AI_REQUESTS_PER_HOUR", "30"))

    def check(self) -> None:
        """Refuse to start a production server with settings that would lose data or leak access."""
        if not self.is_production:
            return
        problems = []
        if len(os.getenv("SECRET_KEY", "")) < 32:
            problems.append("SECRET_KEY must be set to a random string of at least 32 characters")
        if not self.encryption_keys or any(len(k) < 32 for k in self.encryption_keys):
            problems.append("ENCRYPTION_KEY must be set to a Fernet key or a random string of at least 32 characters")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must point to Postgres (SQLite files are wiped on most free hosts)")
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must list the frontend URL")
        if problems:
            raise RuntimeError("Invalid production settings:\n- " + "\n- ".join(problems))


settings = Settings()
