from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, ClassVar

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from fractal_journal.ai_review import DecisionReviewResult, DecisionReviewStatus
from fractal_journal.bar_series import (
    BarSeriesCoverage,
    BarSeriesError,
    BarSeriesRegisterRequest,
    FileBarSeriesStore,
    RegisteredBarsProvider,
    parse_tradingview_csv,
)
from fractal_journal.chart_query import (
    ChartQueryError,
    ChartQueryRecord,
    FileChartQueryStore,
    new_query_record,
)
from fractal_journal.config import Settings
from fractal_journal.daily_query_series import (
    DAILY_CACHE_DIRNAME,
    TOSS_DAILY_CACHE_DIRNAME,
    KisDailyQuerySource,
    TossDailyQuerySource,
    deep_history_throttle,
)
from fractal_journal.fallback_provider import FallbackOhlcvProvider
from fractal_journal.hermes_query import (
    HermesChartQueryService,
    HermesUniverseQueryService,
    create_chart_query_service,
    create_universe_query_service,
)
from fractal_journal.hermes_review import DecisionReviewer, create_hermes_reviewer
from fractal_journal.kis_auth import KisCredentials, load_credentials
from fractal_journal.kis_daily_history import DAILY_TIMEFRAME
from fractal_journal.kis_provider import KisOhlcvProvider
from fractal_journal.provider import FixtureOhlcvProvider, OhlcvProvider
from fractal_journal.review_service import DecisionReviewService
from fractal_journal.schemas import (
    CaptureCreate,
    CaptureDetailResponse,
    CaptureListResponse,
    CaptureResponse,
    ErrorResponse,
    EvidenceDataStatus,
    HealthResponse,
    SessionResponse,
)
from fractal_journal.scoring import ScoreResult, score_capture
from fractal_journal.security import require_token
from fractal_journal.store import (
    CaptureNotFoundError,
    FileCaptureStore,
    InvalidScreenshotError,
)
from fractal_journal.toss_auth import TossCredentials
from fractal_journal.toss_auth import load_credentials as load_toss_credentials
from fractal_journal.toss_provider import TossOhlcvProvider
from fractal_journal.universe_query import (
    FileUniverseQueryStore,
    UniverseQueryError,
    UniverseQueryRecord,
    UniverseScope,
    collect_universe_files,
    new_universe_query_record,
)


@dataclass(frozen=True, slots=True)
class AppServices:
    settings: Settings
    store: FileCaptureStore
    provider: OhlcvProvider
    series_store: FileBarSeriesStore
    review_service: DecisionReviewService
    query_store: FileChartQueryStore
    query_service: HermesChartQueryService
    daily_query_source: KisDailyQuerySource
    universe_query_store: FileUniverseQueryStore
    universe_query_service: HermesUniverseQueryService


def build_ohlcv_provider(
    settings: Settings,
    kis_credentials: KisCredentials | None,
    toss_credentials: TossCredentials | None,
) -> OhlcvProvider:
    """Assemble the market-data chain: Toss primary, KIS fallback, else fixture."""
    chain: list[OhlcvProvider] = []
    if toss_credentials is not None:
        chain.append(
            TossOhlcvProvider(toss_credentials, settings.toss_token_cache_path),
        )
    if kis_credentials is not None:
        chain.append(
            KisOhlcvProvider(kis_credentials, settings.kis_token_cache_path),
        )
    if not chain:
        return FixtureOhlcvProvider()
    if len(chain) == 1:
        return chain[0]
    return FallbackOhlcvProvider(tuple(chain))


def build_daily_query_source(
    settings: Settings,
    kis_credentials: KisCredentials | None,
    toss_credentials: TossCredentials | None,
    default_provider: OhlcvProvider,
) -> KisDailyQuerySource:
    """Assemble the free-query daily source; Toss-primary when credentialed.

    KIS keeps its dedicated gentler page throttle for deep daily paging; the
    Toss provider's default 0.5s cadence is already the safe deep-paging pace.
    """
    kis_daily = (
        KisOhlcvProvider(
            kis_credentials,
            settings.kis_token_cache_path,
            history_throttle=deep_history_throttle,
        )
        if kis_credentials is not None
        else None
    )
    if toss_credentials is not None:
        toss_daily = TossOhlcvProvider(
            toss_credentials,
            settings.toss_token_cache_path,
        )
        provider: OhlcvProvider = (
            FallbackOhlcvProvider((toss_daily, kis_daily))
            if kis_daily is not None
            else toss_daily
        )
        return TossDailyQuerySource(
            provider=provider,
            cache_store=FileBarSeriesStore(
                settings.data_dir,
                dirname=TOSS_DAILY_CACHE_DIRNAME,
            ),
        )
    return KisDailyQuerySource(
        provider=kis_daily if kis_daily is not None else default_provider,
        cache_store=FileBarSeriesStore(
            settings.data_dir,
            dirname=DAILY_CACHE_DIRNAME,
        ),
    )


def create_app(
    settings: Settings | None = None,
    *,
    provider: OhlcvProvider | None = None,
    reviewer: DecisionReviewer | None = None,
    query_service: HermesChartQueryService | None = None,
    universe_query_service: HermesUniverseQueryService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    store = FileCaptureStore(
        resolved_settings.data_dir,
        resolved_settings.screenshot_dir,
    )
    credentials = load_credentials(
        resolved_settings.kis_env_path,
        resolved_settings.kis_app_key,
        resolved_settings.kis_app_secret,
    )
    toss_credentials = load_toss_credentials(
        resolved_settings.kis_env_path,
        resolved_settings.toss_client_id,
        resolved_settings.toss_client_secret,
    )
    resolved_provider = provider or build_ohlcv_provider(
        resolved_settings,
        credentials,
        toss_credentials,
    )
    resolved_reviewer = reviewer or create_hermes_reviewer(resolved_settings)
    series_store = FileBarSeriesStore(resolved_settings.data_dir)
    evidence_provider = RegisteredBarsProvider(series_store, resolved_provider)
    services = AppServices(
        settings=resolved_settings,
        store=store,
        provider=evidence_provider,
        series_store=series_store,
        review_service=DecisionReviewService(evidence_provider, resolved_reviewer),
        query_store=FileChartQueryStore(resolved_settings.data_dir),
        query_service=query_service or create_chart_query_service(resolved_settings),
        universe_query_store=FileUniverseQueryStore(resolved_settings.data_dir),
        universe_query_service=(
            universe_query_service
            or create_universe_query_service(resolved_settings)
        ),
        daily_query_source=(
            # An injected provider (tests) bypasses credential-based assembly
            # and keeps the KIS-named cache directory, as before.
            KisDailyQuerySource(
                provider=resolved_provider,
                cache_store=FileBarSeriesStore(
                    resolved_settings.data_dir,
                    dirname=DAILY_CACHE_DIRNAME,
                ),
            )
            if provider is not None
            else build_daily_query_source(
                resolved_settings,
                credentials,
                toss_credentials,
                resolved_provider,
            )
        ),
    )

    @asynccontextmanager
    async def app_lifespan(_: FastAPI) -> AsyncGenerator[None]:
        services.store.ensure_ready()
        yield

    app = FastAPI(
        title="TradingView Fractal Replay Journal",
        lifespan=app_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8766", "http://localhost:8766"],
        allow_origin_regex=r"chrome-extension://.*",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    _register_routes(app, services)
    return app


def _register_routes(app: FastAPI, services: AppServices) -> None:
    _register_core_routes(app, services)
    _register_capture_routes(app, services)
    _register_score_routes(app, services)
    _register_bar_series_routes(app, services)
    _register_review_history_routes(app, services)
    _register_chart_query_routes(app, services)
    _register_universe_query_routes(app, services)


def _register_core_routes(app: FastAPI, services: AppServices) -> None:
    @app.get("/health")
    async def health() -> HealthResponse:
        services.store.ensure_ready()
        token_cache_state = (
            "configured" if services.settings.kis_token_cache_path else "missing"
        )
        db_status = (
            "local-jsonl"
            if services.settings.database_url == "local-jsonl"
            else "configured"
        )
        return HealthResponse(
            checks={
                "db": db_status,
                "storage": "ok",
                "provider_token_cache": token_cache_state,
                "log_redaction": "ok",
            },
        )

    @app.get("/api/sessions/current")
    async def current_session(
        _: Annotated[None, Depends(_check_auth(services))],
    ) -> SessionResponse:
        return SessionResponse()


def _register_capture_routes(app: FastAPI, services: AppServices) -> None:
    @app.post(
        "/api/captures",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_capture(
        payload: CaptureCreate,
        _: Annotated[None, Depends(_check_write_auth(services))],
    ) -> CaptureResponse:
        try:
            capture = services.store.create_capture(payload)
        except InvalidScreenshotError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.reason,
            ) from exc
        return CaptureResponse(capture=capture)

    @app.get("/api/captures/{capture_id}")
    async def get_capture(
        capture_id: str,
        _: Annotated[None, Depends(_check_auth(services))],
    ) -> CaptureDetailResponse:
        try:
            capture = services.store.get_capture(capture_id)
        except CaptureNotFoundError as exc:
            raise _not_found(exc.capture_id) from exc
        score_status = (
            "ready" if services.store.load_score(capture_id) is not None else "pending"
        )
        stored_review = services.store.load_decision_review(capture_id)
        review_status = (
            stored_review.status.value if stored_review is not None else "pending"
        )
        return CaptureDetailResponse(
            capture=capture,
            score_status=score_status,
            ai_review_status=review_status,
        )

    @app.get("/api/captures")
    async def list_captures(
        _: Annotated[None, Depends(_check_auth(services))],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> CaptureListResponse:
        return CaptureListResponse(captures=services.store.list_captures(limit))


def _register_score_routes(app: FastAPI, services: AppServices) -> None:
    @app.post("/api/captures/{capture_id}/score")
    async def create_score(
        capture_id: str,
        _: Annotated[None, Depends(_check_write_auth(services))],
    ) -> ScoreResult:
        try:
            capture = services.store.get_capture(capture_id)
        except CaptureNotFoundError as exc:
            raise _not_found(exc.capture_id) from exc
        return services.store.save_score(score_capture(capture, services.provider))

    @app.get("/api/captures/{capture_id}/score")
    async def get_score(
        capture_id: str,
        _: Annotated[None, Depends(_check_auth(services))],
    ) -> ScoreResult | ErrorResponse:
        score = services.store.load_score(capture_id)
        if score is not None:
            return score
        return ErrorResponse(detail="score_pending")

    @app.post("/api/captures/{capture_id}/ai-review")
    def create_ai_review(
        capture_id: str,
        _: Annotated[None, Depends(_check_write_auth(services))],
    ) -> DecisionReviewResult:
        try:
            capture = services.store.get_capture(capture_id)
        except CaptureNotFoundError as exc:
            raise _not_found(exc.capture_id) from exc
        review = services.review_service.review_capture(capture)
        return services.store.save_decision_review(review)

    @app.get("/api/captures/{capture_id}/ai-review")
    async def get_ai_review(
        capture_id: str,
        _: Annotated[None, Depends(_check_auth(services))],
    ) -> DecisionReviewResult | ErrorResponse:
        try:
            capture = services.store.get_capture(capture_id)
        except CaptureNotFoundError as exc:
            raise _not_found(exc.capture_id) from exc
        review = services.store.load_decision_review(str(capture.id))
        if review is not None:
            return review
        return ErrorResponse(detail="ai_review_pending")


class BarSeriesCoverageResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    registered: bool
    coverage: BarSeriesCoverage | None = None


class BarSeriesRegisterResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    coverage: BarSeriesCoverage
    reviews: tuple[DecisionReviewResult, ...]


class ReviewHistoryItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    capture_id: str
    created_at: str
    symbol: str
    symbol_name: str = ""
    timeframe: str
    decision_time_exchange: str
    hypothesis: str
    decision_note: str
    review: DecisionReviewResult | None = None


class ReviewHistoryResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[ReviewHistoryItem, ...]


def _register_review_history_routes(app: FastAPI, services: AppServices) -> None:
    @app.get("/api/reviews")
    async def list_reviews(
        _: Annotated[None, Depends(_check_auth(services))],
        symbol: Annotated[str | None, Query(max_length=32)] = None,
        timeframe: Annotated[str | None, Query(max_length=16)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> ReviewHistoryResponse:
        items: list[ReviewHistoryItem] = []
        for capture in services.store.list_captures(limit=500):
            confirmed = capture.confirmed
            if symbol is not None and symbol not in (
                confirmed.provider_symbol,
                confirmed.symbol,
            ):
                continue
            if timeframe is not None and confirmed.timeframe != timeframe:
                continue
            items.append(
                ReviewHistoryItem(
                    capture_id=str(capture.id),
                    created_at=capture.created_at.isoformat(),
                    symbol=confirmed.symbol,
                    symbol_name=capture.extracted.symbol_name_candidate,
                    timeframe=confirmed.timeframe,
                    decision_time_exchange=confirmed.decision_time_exchange,
                    hypothesis=(
                        capture.decision.value
                        if capture.decision is not None
                        else capture.hypothesis.value
                    ),
                    decision_note=capture.effective_decision_note,
                    review=services.store.load_decision_review(str(capture.id)),
                )
            )
            if len(items) >= limit:
                break
        return ReviewHistoryResponse(items=tuple(items))


def _review_needs_rerun(stored: DecisionReviewResult) -> bool:
    if stored.status is not DecisionReviewStatus.READY:
        return True
    evidence = stored.evidence
    return evidence is None or evidence.data_status is not EvidenceDataStatus.READY


def _register_bar_series_routes(app: FastAPI, services: AppServices) -> None:
    @app.post("/api/bar-series")
    def register_bar_series(
        payload: BarSeriesRegisterRequest,
        _: Annotated[None, Depends(_check_write_auth(services))],
    ) -> BarSeriesRegisterResponse:
        try:
            bars = parse_tradingview_csv(payload.csv_text)
            coverage = services.series_store.register(
                payload.symbol,
                payload.timeframe,
                bars,
            )
        except BarSeriesError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.reason,
            ) from exc
        reviews: list[DecisionReviewResult] = []
        for capture in services.store.list_captures(limit=1000):
            if payload.symbol not in (
                capture.confirmed.provider_symbol,
                capture.confirmed.symbol,
            ):
                continue
            if capture.confirmed.timeframe != payload.timeframe:
                continue
            stored = services.store.load_decision_review(str(capture.id))
            if stored is not None and not _review_needs_rerun(stored):
                continue
            review = services.review_service.review_capture(capture)
            reviews.append(services.store.save_decision_review(review))
        return BarSeriesRegisterResponse(coverage=coverage, reviews=tuple(reviews))

    @app.get("/api/bar-series/coverage")
    async def bar_series_coverage(
        _: Annotated[None, Depends(_check_auth(services))],
        symbol: Annotated[str, Query(min_length=1, max_length=32)],
        timeframe: Annotated[str, Query(min_length=1, max_length=16)],
    ) -> BarSeriesCoverageResponse:
        try:
            coverage = services.series_store.coverage(symbol, timeframe)
        except BarSeriesError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.reason,
            ) from exc
        return BarSeriesCoverageResponse(
            registered=coverage is not None,
            coverage=coverage,
        )


class ChartQueryCreateRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=16)
    question: str = Field(min_length=1, max_length=2_000)
    replay_active: bool = False


class ChartQueryResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    query: ChartQueryRecord


class ChartQueryListResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[ChartQueryRecord, ...]


def _register_chart_query_routes(app: FastAPI, services: AppServices) -> None:
    @app.post("/api/queries", status_code=status.HTTP_201_CREATED)
    def create_chart_query(
        payload: ChartQueryCreateRequest,
        _: Annotated[None, Depends(_check_write_auth(services))],
    ) -> ChartQueryResponse:
        # Replay answers would blend bars past the replay cursor into Lee's
        # training view; the extension blocks this too, but the backend is the
        # authority.
        if payload.replay_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="replay_active",
            )
        bars = services.series_store.load(payload.symbol, payload.timeframe)
        if not bars and payload.timeframe == DAILY_TIMEFRAME:
            # Daily charts are never registrable from the extension (KIS-direct
            # by design), so serve them from the KIS-backed query cache.
            bars = services.daily_query_source.load(payload.symbol)
            if not bars:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="daily_history_unavailable",
                )
        if not bars:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="series_unregistered",
            )
        question = payload.question.strip()
        try:
            answered = services.query_service.ask(
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                question=question,
                bars=bars,
            )
        except ChartQueryError as exc:
            record = new_query_record(
                symbol=payload.symbol,
                timeframe=payload.timeframe,
                question=question,
                status="failed",
                error_code=exc.reason,
                bars=bars,
            )
            services.query_store.append(record)
            return ChartQueryResponse(query=record)
        record = new_query_record(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            question=question,
            status="answered",
            answer=answered.answer,
            model=answered.model,
            bars=bars,
            computations=answered.computations,
        )
        services.query_store.append(record)
        return ChartQueryResponse(query=record)

    @app.get("/api/queries")
    async def list_chart_queries(
        _: Annotated[None, Depends(_check_auth(services))],
        symbol: Annotated[str | None, Query(max_length=32)] = None,
        timeframe: Annotated[str | None, Query(max_length=16)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> ChartQueryListResponse:
        return ChartQueryListResponse(
            items=services.query_store.list_queries(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
            ),
        )


class UniverseQueryCreateRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    scope: UniverseScope
    question: str = Field(min_length=1, max_length=2_000)


class UniverseQueryResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    query: UniverseQueryRecord


class UniverseQueryListResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[UniverseQueryRecord, ...]


def _register_universe_query_routes(app: FastAPI, services: AppServices) -> None:
    @app.post("/api/universe-queries", status_code=status.HTTP_201_CREATED)
    def create_universe_query(
        payload: UniverseQueryCreateRequest,
        _: Annotated[None, Depends(_check_write_auth(services))],
    ) -> UniverseQueryResponse:
        try:
            files = collect_universe_files(
                services.settings.universe_scan_dir,
                services.settings.universe_base_rate_path,
                payload.scope,
            )
        except UniverseQueryError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.reason,
            ) from exc
        question = payload.question.strip()
        file_names = tuple(file.filename for file in files)
        try:
            answered = services.universe_query_service.ask(
                scope=payload.scope,
                question=question,
                files=files,
            )
        except ChartQueryError as exc:
            record = new_universe_query_record(
                scope=payload.scope,
                question=question,
                status="failed",
                error_code=exc.reason,
                data_files=file_names,
            )
            services.universe_query_store.append(record)
            return UniverseQueryResponse(query=record)
        record = new_universe_query_record(
            scope=payload.scope,
            question=question,
            status="answered",
            answer=answered.answer,
            model=answered.model,
            data_files=file_names,
            computations=answered.computations,
        )
        services.universe_query_store.append(record)
        return UniverseQueryResponse(query=record)

    @app.get("/api/universe-queries")
    async def list_universe_queries(
        _: Annotated[None, Depends(_check_auth(services))],
        scope: Annotated[str | None, Query(max_length=16)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> UniverseQueryListResponse:
        return UniverseQueryListResponse(
            items=services.universe_query_store.list_queries(
                scope=scope,
                limit=limit,
            ),
        )


AuthDependency = Callable[[str | None, str | None], None]


def _check_auth(services: AppServices) -> AuthDependency:
    def check_auth(
        authorization: Annotated[str | None, Header()] = None,
        origin: Annotated[str | None, Header()] = None,
    ) -> None:
        require_token(services.settings, authorization, origin)

    return check_auth


def _check_write_auth(services: AppServices) -> AuthDependency:
    def check_write_auth(
        authorization: Annotated[str | None, Header()] = None,
        origin: Annotated[str | None, Header()] = None,
    ) -> None:
        require_token(services.settings, authorization, origin, write=True)

    return check_write_auth


def _not_found(capture_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"capture_not_found:{capture_id}",
    )


app = create_app()
