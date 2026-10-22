from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, func, select

from ..config import settings
from ..database import get_session
from ..demo import create_guest, purge_expired_guests
from ..models import User
from ..ratelimit import SlidingWindowLimiter
from ..schemas import Credentials, TokenOut, UserOut
from ..security import create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
demo_limiter = SlidingWindowLimiter(settings.demo_logins_per_hour)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: Credentials, session: Session = Depends(get_session)) -> TokenOut:
    taken = session.exec(select(User).where(func.lower(User.username) == data.username.lower())).first()
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is already taken")
    user = User(username=data.username, password_hash=hash_password(data.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenOut(access_token=create_token(user), user=UserOut.of(user))


@router.post("/login", response_model=TokenOut)
def login(data: Credentials, session: Session = Depends(get_session)) -> TokenOut:
    user = session.exec(select(User).where(func.lower(User.username) == data.username.lower())).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    return TokenOut(access_token=create_token(user), user=UserOut.of(user))


@router.post("/demo", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def demo(request: Request, session: Session = Depends(get_session)) -> TokenOut:
    """Create a temporary guest account with three synced sample mailboxes. No sign-up needed."""
    if not demo_limiter.hit(request.client.host if request.client else "unknown"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many demo accounts from your network. Try again later.")
    purge_expired_guests(session)
    user = create_guest(session)
    return TokenOut(access_token=create_token(user), user=UserOut.of(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.of(user)
