from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "crypto_mvp"
    db_user: str = "crypto_user"
    db_password: str = "crypto_pass"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    bot_token: str = ""
    webapp_url: str = "http://localhost:8010/webapp/"
    site_url: str = "http://localhost:8010/site/"
    site_auth_secret: str = ""
    site_token_ttl_days: int = 30
    webapp_dev_mode: bool = False
    dev_telegram_user_id: int = 1
    bot_market_sync_interval_seconds: int = 120

    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    coingecko_timeout_seconds: int = 15

    proxy_host: str = ""
    proxy_port: Optional[int] = None
    proxy_username: str = ""
    proxy_password: str = ""
    proxy_fallbacks: str = ""

    @field_validator("proxy_port", mode="before")
    @classmethod
    def normalize_proxy_port(cls, value):
        if value in ("", None):
            return None
        return value

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def proxy_url(self) -> Optional[str]:
        if not self.proxy_host or not self.proxy_port:
            return None
        if self.proxy_username and self.proxy_password:
            return (
                f"http://{self.proxy_username}:{self.proxy_password}"
                f"@{self.proxy_host}:{self.proxy_port}"
            )
        return f"http://{self.proxy_host}:{self.proxy_port}"

    @property
    def proxy_urls(self) -> list[str]:
        urls: list[str] = []
        if self.proxy_url:
            urls.append(self.proxy_url)
        for raw_proxy in self.proxy_fallbacks.split(","):
            proxy = raw_proxy.strip()
            if not proxy:
                continue
            parts = proxy.split(":")
            if len(parts) == 4:
                host, port, username, password = parts
                urls.append(f"http://{username}:{password}@{host}:{port}")
            elif len(parts) == 2:
                host, port = parts
                urls.append(f"http://{host}:{port}")
            elif proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
                urls.append(proxy)
        return list(dict.fromkeys(urls))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
