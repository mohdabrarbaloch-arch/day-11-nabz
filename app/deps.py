"""Shared FastAPI dependencies: current user, ownership guards, rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import Patient, User
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Token is missing a subject.")

    user = db.scalar(select(User).where(User.email == subject))
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return user


def get_owned_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Patient:
    """Fetch a patient, 404 if it isn't the caller's.

    404 rather than 403 on purpose: a 403 confirms the record exists, which
    leaks the presence of another clinician's patient.
    """
    patient = db.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.owner_id == user.id)
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


class SlidingWindowLimiter:
    """In-process sliding-window limiter.

    Honest about its limits: state is per-process, so N workers allow N times
    the configured rate. A shared Redis counter is the production answer; this
    is the correct shape without the dependency.
    """

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window - (now - bucket[0])) + 1
            return False, max(retry_after, 1)
        bucket.append(now)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_dependency(limiter: SlidingWindowLimiter):
    """Build a dependency bound to a specific limiter instance."""

    def _dep(request: Request) -> None:
        allowed, retry_after = limiter.check(_client_key(request))
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Slow down and try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dep


def build_limiters() -> tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    settings = get_settings()
    return (
        SlidingWindowLimiter(settings.rate_limit_per_minute),
        SlidingWindowLimiter(settings.login_rate_limit_per_minute),
    )
