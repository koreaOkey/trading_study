from pathlib import Path
from typing import ClassVar

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Field(
        default=Path("/home/lee/var/tradingview-fractal-replay-journal"),
        validation_alias=AliasChoices("TRFJ_DATA_DIR", "FJ_DATA_DIR"),
    )
    storage_dir: Path = Field(
        default=Path("/home/lee/var/tradingview-fractal-replay-journal/storage"),
        validation_alias=AliasChoices("TRFJ_STORAGE_DIR", "FJ_STORAGE_DIR"),
    )
    screenshot_dir: Path = Field(
        default=Path("/home/lee/var/tradingview-fractal-replay-journal/storage/screenshots"),
        validation_alias=AliasChoices("TRFJ_SCREENSHOT_DIR", "FJ_SCREENSHOT_DIR"),
    )
    kis_token_cache_path: Path = Field(
        default=Path(
            "/home/lee/.cache/tradingview-fractal-replay-journal/kis-token-cache.json",
        ),
        validation_alias=AliasChoices(
            "TRFJ_KIS_TOKEN_CACHE_PATH",
            "FJ_KIS_TOKEN_CACHE_PATH",
        ),
    )
    kis_env_path: Path = Field(default=Path("/home/lee/trading-ta-knowledge/.env"))
    database_url: str = Field(
        default="local-jsonl",
        validation_alias=AliasChoices("TRFJ_DATABASE_URL", "FJ_DATABASE_URL"),
    )
    api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TRFJ_SHARED_API_TOKEN", "FJ_API_TOKEN"),
    )
    kis_app_key: str = Field(default="", validation_alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", validation_alias="KIS_APP_SECRET")
    cors_origins: list[str] = Field(default_factory=lambda: ["chrome-extension://*"])
    allowed_extension_origins: list[str] = Field(default_factory=list)
