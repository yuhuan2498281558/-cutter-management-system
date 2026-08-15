"""Runtime configuration for the Django application.

All deployment-specific values are read from environment variables. Keep
this module free of credentials so it is safe to publish with the project.
"""

import os
from pathlib import Path


def _load_local_env_file(path: str) -> None:
    """Load a local ``KEY=value`` file without overriding real env vars."""

    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env_file(Path(__file__).resolve().parents[1] / ".env.local")


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _get_list(name: str, default=None):
    value = os.environ.get(name)
    if not value:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


DATABASE_ENGINE = os.environ.get("DATABASE_ENGINE", "django.db.backends.postgresql_psycopg2")
DATABASE_NAME = os.environ.get("DATABASE_NAME", os.environ.get("POSTGRES_DB", "daoju"))
DATABASE_HOST = os.environ.get("DATABASE_HOST", "127.0.0.1")
DATABASE_PORT = _get_int("DATABASE_PORT", 5432)
DATABASE_USER = os.environ.get("DATABASE_USER", os.environ.get("POSTGRES_USER", "daoju_user"))
DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))

TABLE_PREFIX = "dvadmin_"

REDIS_DB = _get_int("REDIS_DB", 1)
CELERY_BROKER_DB = _get_int("CELERY_BROKER_DB", 3)
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = _get_int("REDIS_PORT", 6379)
REDIS_AUTH = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
REDIS_URL = os.environ.get("REDIS_URL", f"redis://{REDIS_AUTH}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL",
    f"redis://{REDIS_AUTH}{REDIS_HOST}:{REDIS_PORT}/{CELERY_BROKER_DB}",
)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)

DEBUG = _get_bool("DJANGO_DEBUG", True)
ENABLE_LOGIN_ANALYSIS_LOG = _get_bool("ENABLE_LOGIN_ANALYSIS_LOG", True)
LOGIN_NO_CAPTCHA_AUTH = _get_bool("LOGIN_NO_CAPTCHA_AUTH", True)
ALLOWED_HOSTS = _get_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
COLUMN_EXCLUDE_APPS = []

# Optional AI assistant configuration. The empty API key keeps the feature
# disabled until the operator supplies a provider key at runtime.
AI_LLM_PROVIDER = os.environ.get("AI_LLM_PROVIDER", "deepseek")
AI_LLM_MODEL = os.environ.get("AI_LLM_MODEL", "deepseek-chat")
AI_LLM_BASE_URL = os.environ.get("AI_LLM_BASE_URL", "https://api.deepseek.com/v1")
AI_LLM_API_KEY = os.environ.get("AI_LLM_API_KEY", "")
AI_LLM_TEMPERATURE = os.environ.get("AI_LLM_TEMPERATURE", "0.1")
AI_LLM_TIMEOUT = os.environ.get("AI_LLM_TIMEOUT", "60")
AI_ASSISTANT_ROUTE_MODE = os.environ.get("AI_ASSISTANT_ROUTE_MODE", "hybrid")

# Optional BIMFace integration. No project identifiers or credentials belong
# in source control; configure these only in the deployment environment.
BIMFACE_APP_KEY = os.environ.get("BIMFACE_APP_KEY", "")
BIMFACE_APP_SECRET = os.environ.get("BIMFACE_APP_SECRET", "")
BIMFACE_FILE_ID = os.environ.get("BIMFACE_FILE_ID", "")
