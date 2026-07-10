from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from fractal_journal.ai_review import DecisionReviewResult
from fractal_journal.config import Settings
from fractal_journal.hermes_review import DecisionReviewer, create_hermes_reviewer
from fractal_journal.kis_auth import load_credentials
from fractal_journal.kis_provider import KisOhlcvProvider
from fractal_journal.provider import FixtureOhlcvProvider, OhlcvProvider
from fractal_journal.review_service import DecisionReviewService
from fractal_journal.schemas import (
    CaptureCreate,
    CaptureDetailResponse,
    CaptureListResponse,
    CaptureResponse,
    ErrorResponse,
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


@dataclass(frozen=True, slots=True)
class AppServices:
    settings: Settings
    store: FileCaptureStore
    provider: OhlcvProvider
    review_service: DecisionReviewService


def create_app(
    settings: Settings | None = None,
    *,
    provider: OhlcvProvider | None = None,
    reviewer: DecisionReviewer | None = None,
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
    resolved_provider = provider or (
        KisOhlcvProvider(credentials, resolved_settings.kis_token_cache_path)
        if credentials is not None
        else FixtureOhlcvProvider()
    )
    resolved_reviewer = reviewer or create_hermes_reviewer(resolved_settings)
    services = AppServices(
        settings=resolved_settings,
        store=store,
        provider=resolved_provider,
        review_service=DecisionReviewService(resolved_provider, resolved_reviewer),
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
