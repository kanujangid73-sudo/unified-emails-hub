"""Insights computed on the server from mail the hub already has. Nothing here calls an AI or
leaves the server, so these run automatically on every message:

- categories: Primary (people), Updates (receipts, alerts, codes), Promotions, Newsletters;
- phishing warnings, with the reasons shown to the user;
- the Account Finder: which websites and apps you signed up to, with which address;
- subscriptions: mailing lists you get, how many you read, and how to leave them.

They're transparent rules rather than a model, so every result can be explained ("this came
from a no-reply address and has an unsubscribe link") and tested.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from .models import MailAccount, Message, Thread

CATEGORIES = ("primary", "updates", "promotions", "newsletters")

# ------------------------------------------------------------------ addresses and domains

# Second-level labels used under country domains: yahoo.co.in, bbc.co.uk, gov.in...
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu", "nic", "res"}


def domain_of(email: str) -> str:
    return email.rpartition("@")[2].strip().lower().rstrip(".")


def registrable_domain(domain: str) -> str:
    """deals.shopkart.example -> shopkart.example; mail.yahoo.co.in -> yahoo.co.in"""
    labels = [p for p in domain.lower().split(".") if p]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


_AUTOMATED = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|notifications?|notify|alerts?|updates?|info|news(letter)?|hello|team|"
    r"support|billing|receipts?|orders?|builds?|tracker|calendar|mailer-daemon|postmaster|accounts?|security|"
    r"loot|deals|offers|marketing|promo(tions)?|digest|bounce)([+._-].*)?$",
    re.I,
)


def is_automated(message: Message) -> bool:
    return bool(_AUTOMATED.match(message.from_email.partition("@")[0]) or message.list_unsubscribe)


# ------------------------------------------------------------------ categories

_PROMO = re.compile(
    r"(\d+\s?% off|\bsale\b|\bdeals?\b|\boffers?\b|\bcoupon|\bpromo code|\buse code\b|\bdiscount|free delivery|early access|"
    r"limited time|last chance|\bhurry\b|cashback|\bloot\b|double coins|wishlist|price drop|dropped in price|new arrivals)",
    re.I,
)


def categorize(messages: list[Message]) -> str:
    """Primary when a person wrote it (or you took part); otherwise promotions, newsletters or updates."""
    if any(m.is_sent for m in messages):
        return "primary"  # you're in the conversation
    latest = messages[-1]
    if not is_automated(latest):
        return "primary"
    if _PROMO.search(latest.subject):
        return "promotions"
    if latest.list_unsubscribe or re.search(r"\bunsubscribe\b", latest.body_text[-3000:], re.I):
        return "newsletters"
    return "updates"


# ------------------------------------------------------------------ phishing warnings

_URGENT = re.compile(
    r"(\burgent\b|immediately|within \d+ hours|account (will be |has been )?(suspended|locked|closed|disabled)|"
    r"verify your (identity|account)|unusual (activity|sign-?in)|action required|final notice|confirm your password)",
    re.I,
)
_HTTP_LINK = re.compile(r"""(?:href=["']?|\s|^)(http://[^\s"'<>]+)""", re.I)
_LOOKALIKE_WORDS = ("verify", "secure", "security", "login", "signin", "account", "update", "support", "billing", "auth", "alert")


def suspicion(message: Message) -> list[str]:
    """Reasons a message looks like phishing; empty when nothing stands out."""
    text = f"{message.subject}\n{message.body_text}"
    reasons = []
    domain = registrable_domain(domain_of(message.from_email))
    label = domain.split(".")[0]
    brands = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", message.from_name)]
    for brand in brands:
        # "PayWave Security" <security@paywave-account-verify.example>: the brand's name, padded
        # with words like "verify" or "secure", on a domain that isn't the brand's own.
        if brand in label and label != brand and any(w in label for w in _LOOKALIKE_WORDS):
            reasons.append(f"The sender's address ({domain}) imitates {message.from_name.split()[0]} but isn't its real domain")
            break
    if _URGENT.search(text):
        reasons.append("Uses urgent or threatening language to rush you")
    if _HTTP_LINK.search(message.body_html or "") or _HTTP_LINK.search(message.body_text):
        reasons.append("Contains a link that isn't encrypted (http://)")
    strong = any("imitates" in r for r in reasons)
    return reasons if strong or len(reasons) >= 2 else []


def analyze(thread: Thread, messages: list[Message]) -> None:
    """Fill in the thread's category and phishing warning from its messages."""
    thread.category = categorize(messages)
    reasons: list[str] = []
    for message in messages:
        if not message.is_sent:
            reasons += [r for r in suspicion(message) if r not in reasons]
    thread.suspicious_reasons = json.dumps(reasons) if reasons else ""


def backfill(session: Session, batch: int = 200) -> int:
    """Analyse threads stored before insights existed (category still NULL)."""
    done = 0
    while True:
        threads = session.exec(select(Thread).where(Thread.category == None).limit(batch)).all()  # noqa: E711
        if not threads:
            return done
        ids = [t.id for t in threads]
        by_thread: dict[int, list[Message]] = defaultdict(list)
        for m in session.exec(select(Message).where(Message.thread_id.in_(ids)).order_by(Message.sent_at, Message.id)):
            by_thread[m.thread_id].append(m)
        for thread in threads:
            if by_thread[thread.id]:
                analyze(thread, by_thread[thread.id])
            else:
                thread.category = "primary"
            session.add(thread)
        session.commit()
        done += len(threads)


# ------------------------------------------------------------------ Account Finder

_SIGNALS = {
    "signup": re.compile(
        r"(welcome to|welcome aboard|verify your (email|address)|confirm your (email|account|address|registration)|"
        r"activate your account|account (has been |was )?created|thanks for (signing up|joining|registering)|"
        r"complete your (sign ?up|registration)|your .{1,40} account is (ready|live))",
        re.I,
    ),
    "security": re.compile(r"(password (was |has been )?(changed|reset|updated)|reset your .{0,30}password|new (sign-?in|login|device)|security alert)", re.I),
    "code": re.compile(r"(verification code|one[- ]time (password|code)|\botp\b|login code|security code|^\s*\d{4,8} is your)", re.I),
    "activity": re.compile(r"(\border\b|receipt|invoice|booking|payment|debited|credited|subscription|certificate|statement|renewal)", re.I),
}
SIGNAL_LABELS = {"signup": "Signed up", "security": "Password or sign-in alert", "code": "Login codes", "activity": "Orders or activity"}
_NAME_NOISE = re.compile(r"\b(security|alerts?|team|deals|support|notifications?|updates?|no-?reply|mailer|accounts?|billing|news|hello)\b", re.I)


def signals_of(message: Message) -> list[str]:
    return [name for name, pattern in _SIGNALS.items() if pattern.search(message.subject)]


@dataclass
class AccountUse:
    account_id: int
    email: str
    color: str
    first_seen: datetime
    last_seen: datetime
    signals: set[str] = field(default_factory=set)
    messages: int = 0
    thread_id: int | None = None  # the most telling message, e.g. the welcome email


@dataclass
class Service:
    domain: str
    names: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    uses: dict[int, AccountUse] = field(default_factory=dict)

    @property
    def name(self) -> str:
        if self.names:
            return max(self.names.items(), key=lambda kv: kv[1])[0]
        return self.domain.split(".")[0].capitalize()


def find_accounts(session: Session, user_id: int) -> list[Service]:
    """Which services each of the user's addresses has an account with, from the mail they sent.

    Evidence counts only when it comes from an automated sender (people's mail never makes a
    "service"), and never from a conversation flagged as phishing (a fake "PayWave" email is not
    a PayWave account).
    """
    accounts = {a.id: a for a in session.exec(select(MailAccount).where(MailAccount.user_id == user_id))}
    rows = session.exec(
        select(Message, Thread.suspicious_reasons)
        .join(Thread, Thread.id == Message.thread_id)
        .where(Thread.user_id == user_id, Message.is_sent == False)  # noqa: E712
        .order_by(Message.sent_at)
    ).all()
    services: dict[str, Service] = {}
    for message, suspicious in rows:
        if suspicious or not is_automated(message):
            continue
        signals = signals_of(message)
        if not signals:
            continue
        domain = registrable_domain(domain_of(message.from_email))
        account = accounts.get(message.account_id)
        if not domain or account is None:
            continue
        service = services.setdefault(domain, Service(domain))
        name = " ".join(_NAME_NOISE.sub(" ", message.from_name).split())
        if name:
            service.names[name] += 1
        use = service.uses.get(account.id)
        if use is None:
            use = service.uses[account.id] = AccountUse(account.id, account.email, account.color, message.sent_at, message.sent_at)
        use.last_seen = message.sent_at
        use.messages += 1
        use.signals.update(signals)
        if use.thread_id is None or "signup" in signals:
            use.thread_id = message.thread_id
    return sorted(services.values(), key=lambda s: s.name.lower())


# ------------------------------------------------------------------ subscriptions


@dataclass
class Subscription:
    domain: str
    name: str
    count: int = 0
    unread: int = 0
    last_seen: datetime | None = None
    unsubscribe_url: str | None = None
    unsubscribe_mailto: str | None = None
    thread_ids: list[int] = field(default_factory=list)
    accounts: set[int] = field(default_factory=set)


_ANGLE = re.compile(r"<([^>]+)>")
_BODY_UNSUB = re.compile(r"(https://[^\s\"'<>]*unsubscribe[^\s\"'<>]*)", re.I)


def unsubscribe_targets(message: Message) -> tuple[str | None, str | None]:
    """The https link and mailto address from List-Unsubscribe, or a link from the body."""
    url = mailto = None
    for target in _ANGLE.findall(message.list_unsubscribe):
        if target.lower().startswith("https://") and not url:
            url = target
        elif target.lower().startswith("mailto:") and not mailto:
            mailto = target
    if not url and not mailto:
        found = _BODY_UNSUB.search(message.body_html or message.body_text)
        url = found.group(1).replace("&amp;", "&") if found else None
    return url, mailto


def subscriptions(session: Session, user_id: int) -> list[Subscription]:
    """Mailing lists and promotions, grouped by sender, busiest first."""
    threads = session.exec(
        select(Thread).where(Thread.user_id == user_id, Thread.category.in_(("newsletters", "promotions")))
    ).all()
    if not threads:
        return []
    latest: dict[int, Message] = {}
    for m in session.exec(select(Message).where(Message.thread_id.in_([t.id for t in threads])).order_by(Message.sent_at, Message.id)):
        latest[m.thread_id] = m
    groups: dict[str, Subscription] = {}
    for thread in threads:
        message = latest.get(thread.id)
        if message is None or thread.suspicious_reasons:
            continue
        domain = registrable_domain(domain_of(message.from_email))
        group = groups.setdefault(domain, Subscription(domain=domain, name=message.from_name or domain))
        group.count += 1
        group.unread += thread.unread_count > 0
        group.thread_ids.append(thread.id)
        group.accounts.add(thread.account_id)
        if group.last_seen is None or message.sent_at > group.last_seen:
            group.last_seen = message.sent_at
            group.name = message.from_name or domain
        url, mailto = unsubscribe_targets(message)
        group.unsubscribe_url = group.unsubscribe_url or url
        group.unsubscribe_mailto = group.unsubscribe_mailto or mailto
    return sorted(groups.values(), key=lambda g: (-g.count, g.name.lower()))
