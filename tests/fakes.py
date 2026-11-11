from app.core.config import Settings


def make_settings(**overrides) -> Settings:
    values = dict(
        app_env="development",
        pg_user="test",
        pg_password="test",
        pg_db="test",
        pg_port=5432,
        pg_host="localhost",
        allowed_origins=["https://app.example.com"],
        allow_insecure_cookies=False,
        session_ttl_seconds=2592000,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)
