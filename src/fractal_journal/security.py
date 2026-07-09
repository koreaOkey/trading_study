from typing import Annotated

from fastapi import Header, HTTPException, status

from fractal_journal.config import Settings


def require_token(
    settings: Settings,
    authorization: Annotated[str | None, Header()] = None,
    _origin: str | None = None,
    write: bool = False,
) -> None:
    if not settings.api_token:
        if not write:
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api_token_required",
        )
    expected = f"Bearer {settings.api_token}"
    if authorization == expected:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_api_token",
    )
