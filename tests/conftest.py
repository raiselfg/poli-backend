import pytest

SETTINGS_ENV_VARS = (
    "APP_ENV",
    "PG_USER",
    "PG_PASSWORD",
    "PG_DB",
    "PG_PORT",
    "PG_HOST",
    "ALLOWED_ORIGINS",
    "ALLOW_INSECURE_COOKIES",
    "SESSION_TTL_SECONDS",
)


@pytest.fixture(autouse=True)
def clean_settings_env(monkeypatch):
    """Keep Settings construction hermetic: tests pass every field explicitly."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
