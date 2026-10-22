"""Password hashing (PBKDF2, standard library) and JWT access tokens."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from .config import settings
from .database import get_session
from .models import User

ALGORITHM = "HS256"
ITERATIONS = 240_000
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def create_token(user: User) -> str:
    # Guest tokens end when the guest account is deleted.
    minutes = settings.guest_ttl_hours * 60 if user.is_guest else settings.token_expire_minutes
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": str(user.id), "name": user.username, "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def user_from_token(token: str, session: Session) -> User | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return session.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    user = user_from_token(credentials.credentials, session) if credentials else None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
