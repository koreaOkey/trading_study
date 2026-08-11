"""DI assembly: Toss-first provider chain and daily query source wiring."""

from pathlib import Path

from fractal_journal.config import Settings
from fractal_journal.daily_query_series import (
    KisDailyQuerySource,
    TossDailyQuerySource,
)
from fractal_journal.fallback_provider import FallbackOhlcvProvider
from fractal_journal.kis_auth import AppKey, AppSecret, KisCredentials
from fractal_journal.kis_provider import KisOhlcvProvider
from fractal_journal.main import build_daily_query_source, build_ohlcv_provider
from fractal_journal.provider import FixtureOhlcvProvider
from fractal_journal.toss_auth import ClientId, ClientSecret, TossCredentials
from fractal_journal.toss_provider import TossOhlcvProvider

KIS_CREDENTIALS = KisCredentials(app_key=AppKey("key"), app_secret=AppSecret("secret"))
TOSS_CREDENTIALS = TossCredentials(
    client_id=ClientId("id"),
    client_secret=ClientSecret("secret"),
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        kis_env_path=tmp_path / "missing.env",
    )


def test_both_credentials_assemble_toss_first_chain(tmp_path: Path) -> None:
    # When
    provider = build_ohlcv_provider(
        _settings(tmp_path),
        KIS_CREDENTIALS,
        TOSS_CREDENTIALS,
    )

    # Then
    assert isinstance(provider, FallbackOhlcvProvider)
    assert isinstance(provider.providers[0], TossOhlcvProvider)
    assert isinstance(provider.providers[1], KisOhlcvProvider)
    assert len(provider.providers) == 2


def test_toss_only_credentials_use_toss_directly(tmp_path: Path) -> None:
    # When
    provider = build_ohlcv_provider(_settings(tmp_path), None, TOSS_CREDENTIALS)

    # Then
    assert isinstance(provider, TossOhlcvProvider)


def test_kis_only_credentials_keep_kis_path(tmp_path: Path) -> None:
    # When
    provider = build_ohlcv_provider(_settings(tmp_path), KIS_CREDENTIALS, None)

    # Then
    assert isinstance(provider, KisOhlcvProvider)


def test_no_credentials_fall_back_to_fixture(tmp_path: Path) -> None:
    # When
    provider = build_ohlcv_provider(_settings(tmp_path), None, None)

    # Then
    assert isinstance(provider, FixtureOhlcvProvider)


def test_daily_source_with_toss_credentials_is_toss_primary(tmp_path: Path) -> None:
    # When
    source = build_daily_query_source(
        _settings(tmp_path),
        KIS_CREDENTIALS,
        TOSS_CREDENTIALS,
        FixtureOhlcvProvider(),
    )

    # Then
    assert isinstance(source, TossDailyQuerySource)
    assert isinstance(source.provider, FallbackOhlcvProvider)
    assert isinstance(source.provider.providers[0], TossOhlcvProvider)
    assert isinstance(source.provider.providers[1], KisOhlcvProvider)
    cache_path = source.cache_store.series_path("005930", "1D")
    assert "toss_daily_query_cache" in str(cache_path)


def test_daily_source_without_kis_uses_toss_alone(tmp_path: Path) -> None:
    # When
    source = build_daily_query_source(
        _settings(tmp_path),
        None,
        TOSS_CREDENTIALS,
        FixtureOhlcvProvider(),
    )

    # Then
    assert isinstance(source, TossDailyQuerySource)
    assert isinstance(source.provider, TossOhlcvProvider)


def test_daily_source_without_toss_keeps_kis_cache_dir(tmp_path: Path) -> None:
    # When
    source = build_daily_query_source(
        _settings(tmp_path),
        KIS_CREDENTIALS,
        None,
        FixtureOhlcvProvider(),
    )

    # Then
    assert type(source) is KisDailyQuerySource
    assert isinstance(source.provider, KisOhlcvProvider)
    cache_path = source.cache_store.series_path("005930", "1D")
    assert "kis_daily_query_cache" in str(cache_path)


def test_daily_source_without_credentials_uses_default_provider(
    tmp_path: Path,
) -> None:
    # Given
    fixture = FixtureOhlcvProvider()

    # When
    source = build_daily_query_source(_settings(tmp_path), None, None, fixture)

    # Then
    assert type(source) is KisDailyQuerySource
    assert source.provider is fixture
