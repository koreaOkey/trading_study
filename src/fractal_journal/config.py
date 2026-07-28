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
    hermes_python_path: Path = Field(
        default=Path("/home/lee/hermes-agent/venv/bin/python3"),
        validation_alias="TRFJ_HERMES_PYTHON_PATH",
    )
    hermes_worker_path: Path = Field(
        default=Path("/home/lee/tradingview-fractal-replay-journal")
        / "src/fractal_journal/hermes_worker.py",
        validation_alias="TRFJ_HERMES_WORKER_PATH",
    )
    hermes_home: Path = Field(
        default=Path("/home/lee/.hermes/profiles/trading"),
        validation_alias="TRFJ_HERMES_HOME",
    )
    hermes_query_worker_path: Path = Field(
        default=Path("/home/lee/tradingview-fractal-replay-journal")
        / "src/fractal_journal/hermes_query_worker.py",
        validation_alias="TRFJ_HERMES_QUERY_WORKER_PATH",
    )
    hermes_timeout_seconds: float = Field(
        default=180.0,
        ge=1.0,
        le=1800.0,
        validation_alias="TRFJ_HERMES_TIMEOUT_SECONDS",
    )
    # Free-form queries run a multi-round code-execution loop (up to 4
    # sandboxed runs plus one LLM call per round), so they get a longer budget
    # than single-shot reviews.
    hermes_query_timeout_seconds: float = Field(
        default=600.0,
        ge=1.0,
        le=1800.0,
        validation_alias="TRFJ_HERMES_QUERY_TIMEOUT_SECONDS",
    )
    hermes_output_max_bytes: int = Field(
        default=64_000,
        ge=1_024,
        le=1_000_000,
        validation_alias="TRFJ_HERMES_OUTPUT_MAX_BYTES",
    )
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
