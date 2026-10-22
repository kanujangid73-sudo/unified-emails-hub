from fastapi import APIRouter, Depends
from sqlmodel import Session

from .. import ai, insights
from ..config import settings
from ..database import get_session
from ..models import User
from ..schemas import AccountFinderOut, AccountUseOut, AIStatus, ServiceOut, SubscriptionOut
from ..security import get_current_user

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/accounts", response_model=AccountFinderOut)
def account_finder(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> AccountFinderOut:
    """Websites and apps you have accounts with, and which of your addresses each one uses.

    Found from welcome, verification, password and order emails in every connected mailbox.
    """
    services = [
        ServiceOut(
            name=s.name,
            domain=s.domain,
            accounts=[
                AccountUseOut(
                    account_id=u.account_id,
                    email=u.email,
                    color=u.color,
                    first_seen=u.first_seen,
                    last_seen=u.last_seen,
                    signals=sorted(u.signals, key=list(insights.SIGNAL_LABELS).index),
                    messages=u.messages,
                    thread_id=u.thread_id,
                )
                for u in sorted(s.uses.values(), key=lambda u: u.first_seen)
            ],
        )
        for s in insights.find_accounts(session, user.id)
    ]
    return AccountFinderOut(services=services, signal_labels=insights.SIGNAL_LABELS)


@router.get("/subscriptions", response_model=list[SubscriptionOut])
def subscriptions(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[SubscriptionOut]:
    """Newsletters and promotions grouped by sender, with how to unsubscribe from each."""
    return [
        SubscriptionOut(
            name=g.name,
            domain=g.domain,
            count=g.count,
            unread=g.unread,
            last_seen=g.last_seen,
            unsubscribe_url=g.unsubscribe_url,
            unsubscribe_mailto=g.unsubscribe_mailto,
            thread_ids=g.thread_ids,
            account_ids=sorted(g.accounts),
        )
        for g in insights.subscriptions(session, user.id)
    ]


@router.get("/ai", response_model=AIStatus)
def ai_status() -> AIStatus:
    """Which assistant answers summary and draft requests."""
    return AIStatus(
        provider=ai.provider(),
        model=settings.gemini_model if ai.provider() == "gemini" else None,
        requests_per_hour=settings.ai_requests_per_hour,
    )
