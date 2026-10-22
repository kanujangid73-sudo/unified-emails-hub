"""Sample mailboxes for the one-click demo.

Three mailboxes with a few hundred realistic messages: a personal Gmail, a work Outlook and
an old IMAP account. Every company and person here is fictional and every domain ends in
.example (reserved for documentation), so nothing points at a real business.

The content is chosen to exercise the whole app:
- conversations with replies, so threading shows up;
- sign-up, verification and password-reset mail from many services, spread over two
  addresses (one service on both), which the planned Account Finder will detect;
- HTML newsletters with remote images and tracking pixels, which the reader blocks;
- a phishing attempt, for the planned AI triage;
- a few messages dated minutes *after* the account was created, so they arrive on a later
  sync and show incremental sync working.

Times are offsets from an anchor (the moment the demo account was created), so every guest
gets a mailbox that looks recent. The same anchor always produces the same mailbox.
"""

import random
from datetime import datetime, timedelta

from .providers.base import Address, RemoteMessage

HOUR = 60
DAY = 24 * HOUR


def ago(days: float = 0, hours: float = 0, minutes: float = 0) -> int:
    """Minutes before the anchor."""
    return -round(days * DAY + hours * HOUR + minutes)


def later(minutes: float) -> int:
    """Minutes after the anchor: delivered on a sync that happens after that time."""
    return round(minutes)


# Entry in a thread: (sender, minutes from anchor, text body[, html body]). A sender of None
# means the mailbox owner wrote it.
Entry = tuple


class MailboxBuilder:
    def __init__(self, prefix: str, owner: Address, anchor: datetime) -> None:
        self.prefix = prefix
        self.owner = owner
        self.anchor = anchor
        self.messages: list[RemoteMessage] = []
        self._threads = 0

    def thread(
        self, subject: str, *entries: Entry, read: bool = True, starred: bool = False, archived: bool = False, unsubscribe: str = ""
    ) -> None:
        """Add a conversation. When read is False, its latest message is unread."""
        self._threads += 1
        thread_id = f"{self.prefix}-t{self._threads}"
        last_other = None
        for index, (sender, minutes, text, *rest) in enumerate(entries):
            sent_by_owner = sender is None
            is_last = index == len(entries) - 1
            to = (last_other or Address("team@example.com"),) if sent_by_owner else (self.owner,)
            if not sent_by_owner:
                last_other = sender
            self.messages.append(
                RemoteMessage(
                    remote_id=f"{thread_id}-m{index + 1}",
                    thread_id=thread_id,
                    sender=self.owner if sent_by_owner else sender,
                    to=to,
                    subject=subject if index == 0 else f"Re: {subject}",
                    sent_at=self.anchor + timedelta(minutes=minutes),
                    body_text=text,
                    body_html=rest[0] if rest else "",
                    is_read=sent_by_owner or read or not is_last,
                    is_starred=starred and is_last,
                    is_archived=archived,
                    list_unsubscribe=unsubscribe,
                )
            )

    def single(self, sender: Address, minutes: int, subject: str, text: str, html: str = "", **flags) -> None:
        self.thread(subject, (sender, minutes, text, html), **flags)

    def build(self) -> list[RemoteMessage]:
        return sorted(self.messages, key=lambda m: (m.sent_at, m.remote_id))


# ---------------------------------------------------------------- shared senders and helpers


def noreply(service: str, domain: str) -> Address:
    return Address(f"no-reply@{domain}", service)


def welcome(box: MailboxBuilder, service: str, domain: str, what: str, minutes: int, verify: bool = True) -> None:
    """The mail every sign-up produces: a verification code and a welcome note."""
    sender = noreply(service, domain)
    if verify:
        box.single(
            sender,
            minutes,
            f"Verify your email for {service}",
            f"Hi,\n\nThanks for signing up for {service}. Confirm this address with the link below "
            f"to finish creating your account.\n\nhttps://{domain}/verify?token=demo\n\n"
            f"If you didn't create a {service} account, you can ignore this email.\n\nThe {service} team",
        )
    box.single(
        sender,
        minutes + 3,
        f"Welcome to {service}!",
        f"Your {service} account is ready.\n\n{what}\n\nHappy to have you,\nThe {service} team",
        _card_html(service, f"Welcome to {service}!", what, f"https://{domain}/start", "Get started"),
    )


def _card_html(brand: str, title: str, text: str, link: str, button: str, color: str = "#4f46e5") -> str:
    return f"""<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#1f2937">
  <div style="background:{color};color:#fff;padding:18px 24px;font-size:20px;font-weight:bold">{brand}</div>
  <div style="padding:24px;border:1px solid #e5e7eb;border-top:0">
    <h2 style="margin-top:0">{title}</h2>
    <p style="line-height:1.6">{text}</p>
    <p><a href="{link}" style="background:{color};color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">{button}</a></p>
  </div>
</div>"""


def _newsletter_html(name: str, domain: str, color: str, issue: int, items: list[tuple[str, str]]) -> str:
    """A typical marketing newsletter: a remote banner image, links, and a 1x1 tracking pixel."""
    rows = "".join(
        f'<tr><td style="padding:12px 0;border-bottom:1px solid #e5e7eb">'
        f'<a href="https://{domain}/r/{issue}/{i}" style="color:{color};font-weight:bold;font-size:16px;text-decoration:none">{title}</a>'
        f'<p style="margin:6px 0 0;color:#4b5563;line-height:1.5">{summary}</p></td></tr>'
        for i, (title, summary) in enumerate(items)
    )
    return f"""<table width="100%" cellpadding="0" cellspacing="0" style="font-family:Georgia,serif;max-width:600px;margin:auto">
  <tr><td><img src="https://cdn.{domain}/banner/{issue}.png" width="600" alt="{name}" style="width:100%;display:block"></td></tr>
  <tr><td style="padding:8px 0 0;color:#6b7280;font-size:13px">Issue #{issue}</td></tr>
  {rows}
  <tr><td style="padding:20px 0;color:#9ca3af;font-size:12px">
    You're receiving this because you subscribed to {name}.
    <a href="https://{domain}/unsubscribe?u=demo" style="color:#9ca3af">Unsubscribe</a>
  </td></tr>
</table>
<img src="https://track.{domain}/open.gif?u=demo&amp;i={issue}" width="1" height="1" alt="">"""


def _plain(items: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"{title}\n{summary}" for title, summary in items)


def newsletter(box, name, domain, color, start_days, every_days, count, topics, rng) -> None:
    sender = Address(f"hello@{domain}", name)
    for issue in range(count):
        picks = rng.sample(topics, 3)
        days = start_days - issue * every_days
        if days < 0:
            break
        number = 100 + issue
        box.single(
            sender,
            ago(days, hours=rng.randint(0, 4)),
            f"{name} #{number}: {picks[0][0]}",
            _plain(picks) + f"\n\nUnsubscribe: https://{domain}/unsubscribe?u=demo",
            _newsletter_html(name, domain, color, number, picks),
            read=days > 3 or rng.random() < 0.3,
            archived=days > 30,
            unsubscribe=f"<https://{domain}/unsubscribe?u=demo>, <mailto:unsubscribe@{domain}>",
        )


def otp(box, service, domain, minutes, rng) -> None:
    code = rng.randint(100000, 999999)
    box.single(
        noreply(service, domain),
        minutes,
        f"{code} is your {service} verification code",
        f"Your {service} verification code is {code}.\n\nIt expires in 10 minutes. "
        f"Never share this code with anyone, including {service} staff.",
        archived=True,
    )


# ---------------------------------------------------------------- personal Gmail

TECH_TOPICS = [
    ("WebAssembly goes mainstream", "Three big frameworks now ship WASM builds by default. What it means for your stack."),
    ("Postgres 19 is out", "Faster vacuum, better JSON indexes and a new incremental backup tool."),
    ("The quiet rise of local AI", "Small open models now run on a laptop CPU. We tested five of them."),
    ("Why your API needs idempotency keys", "Retries are inevitable. Here is how payment companies make them safe."),
    ("OAuth, explained with a hotel key card", "The clearest mental model for access and refresh tokens we've seen."),
    ("SQLite in production?", "More teams are running it at the edge. The trade-offs, honestly."),
    ("React compiler, one year later", "Did auto-memoization deliver? Benchmarks from real apps."),
    ("Rust in the Linux kernel", "The first drivers are shipping. A look at what changed."),
    ("Designing for slow networks", "Lessons from building apps for 2G users in rural India."),
]

PYTHON_TOPICS = [
    ("Free-threaded Python in practice", "We removed the GIL from a web service. Here are the numbers."),
    ("FastAPI dependency tricks", "Five patterns for cleaner request handling and testing."),
    ("Typing your SQL queries", "SQLModel, SQLAlchemy 2 and how far type checkers can follow."),
    ("asyncio TaskGroups", "Structured concurrency finally makes background work easy to reason about."),
    ("Pytest fixtures that scale", "How large codebases keep test setup fast and readable."),
    ("Packaging with uv", "From requirements.txt to lockfiles in an afternoon."),
]

DEALS = [
    ("Up to 60% off headphones", "Top brands, today only."),
    ("Your wishlist item dropped in price", "The backpack you saved is now ₹1,499."),
    ("Weekend sale: home & kitchen", "Free delivery on orders above ₹499."),
    ("Last chance: festive offers end tonight", "Extra 10% off with PayWave."),
    ("New arrivals in sneakers", "Fresh styles picked for you."),
    ("Members-only early access", "Shop the big sale a day before everyone else."),
]


def personal_mailbox(owner: Address, anchor: datetime) -> list[RemoteMessage]:
    rng = random.Random("personal")
    box = MailboxBuilder("gm", owner, anchor)

    priya = Address("priya.sharma@example.net", "Priya Sharma")
    rohan = Address("rohan.mehta@example.net", "Rohan Mehta")
    mom = Address("sunita.morgan@example.net", "Mom")
    sam = Address("sam.lee@example.org", "Sam Lee")
    landlord = Address("rentals@greenview.example", "Greenview Apartments")

    # Conversations
    box.thread(
        "Weekend trip to the hills?",
        (priya, ago(6, 9), "Hey! A few of us are planning a trip to the hills next weekend. Leaving Friday night, back Sunday. You in?"),
        (None, ago(6, 7), "Count me in! Should I book the homestay we stayed at last time?"),
        (priya, ago(6, 5), "Yes please, it was perfect. 4 people, 2 nights. I'll handle the train tickets."),
        (None, ago(5, 22), "Booked the homestay: 2 rooms, Friday and Saturday night. Sharing the confirmation in the group."),
        (priya, ago(5, 20), "You're a star. Packing list coming soon 🎒"),
        starred=True,
    )
    box.thread(
        "Dinner on Sunday?",
        (mom, ago(3, 4), "Beta, are you coming for dinner this Sunday? I'm making rajma chawal. Bring Priya if she's free."),
        (None, ago(3, 2), "Of course! I'll be there by 7. Priya is away that weekend, she says hi."),
        (mom, ago(2, 23), "Okay. Don't forget to bring back my steel dabba 😄"),
        read=False,
    )
    box.thread(
        "Photos from the trek",
        (rohan, ago(12, 3), "Uploaded all the photos from the trek. The sunrise ones came out amazing.\n\nAlbum: https://photos.example/album/trek-demo"),
        (None, ago(12, 1), "These are incredible. The one at the summit is going on my wall."),
    )
    box.thread(
        "Book recommendation",
        (sam, ago(20), "You asked for something to read on the train. Try 'The Pragmatic Programmer', 20th anniversary edition. Short chapters, perfect for commutes."),
        (None, ago(19, 20), "Ordered it. Thanks Sam!"),
        archived=True,
    )
    box.single(
        landlord,
        ago(15, 6),
        "Rent receipt for this month",
        "Dear Alex,\n\nWe have received your rent payment of ₹18,000. Your receipt is attached to your tenant portal.\n\nRegards,\nGreenview Apartments",
        archived=True,
    )
    box.single(
        rohan,
        ago(1, 3),
        "Cricket this Saturday?",
        "Morning match at the usual ground, 7 AM. We're one player short. Reply if you can make it!",
        read=False,
    )

    # Accounts created with this address (for the Account Finder)
    welcome(box, "Zestro", "zestro.example", "Order from 5,000+ restaurants near you, with live delivery tracking.", ago(70, 5))
    welcome(box, "StreamBox", "streambox.example", "Your first month is free. Start watching on any device.", ago(64, 2))
    welcome(box, "ShopKart", "shopkart.example", "Millions of products, delivered fast.", ago(58, 8), verify=False)
    welcome(box, "PayWave", "paywave.example", "Send money, pay bills and split expenses in seconds.", ago(50, 1))
    welcome(box, "FitPulse", "fitpulse.example", "Your 30-day running plan starts tomorrow.", ago(33, 7))
    welcome(box, "TripTrail", "triptrail.example", "Plan trips, book trains and keep every ticket in one place.", ago(9, 4))
    box.single(
        noreply("StreamBox", "streambox.example"),
        ago(27, 2),
        "Your StreamBox password was changed",
        "The password for your StreamBox account was just changed.\n\nIf this was you, no action is needed. "
        "If not, reset your password right away: https://streambox.example/reset",
        archived=True,
    )

    # Orders, payments and codes
    restaurants = ["Spice Route", "Pizza Planet", "Green Bowl", "Tandoor Nights", "Sushi Sora", "Burger Barn"]
    for i, days in enumerate([66, 52, 40, 29, 17, 8, 2]):
        place = restaurants[i % len(restaurants)]
        amount = rng.randint(240, 890)
        box.thread(
            f"Your order from {place}",
            (noreply("Zestro", "zestro.example"), ago(days, 1), f"Order confirmed! {place} is preparing your food. Total: ₹{amount}."),
            (noreply("Zestro", "zestro.example"), ago(days, 0, 25), f"Delivered. Enjoy your meal from {place}! Rate your order to help others."),
            archived=days > 3,
        )
    products = [("Noise-cancelling headphones", 4999), ("Running shoes", 3299), ("The Pragmatic Programmer", 699)]
    for i, (item, price) in enumerate(products):
        days = 48 - i * 18
        order = f"SK-{rng.randint(1000000, 9999999)}"
        receipt = _card_html("ShopKart", f"Order {order} confirmed", f"{item}<br>Total paid: ₹{price:,}", "https://shopkart.example/orders", "Track order", "#f59e0b")
        box.thread(
            f"Order {order}: {item}",
            (noreply("ShopKart", "shopkart.example"), ago(days, 6), f"Thanks for your order!\n\n{item}\nTotal paid: ₹{price:,}", receipt),
            (noreply("ShopKart", "shopkart.example"), ago(days - 1, 2), f"Your order {order} has shipped and arrives in 2 days."),
            (noreply("ShopKart", "shopkart.example"), ago(days - 3, 5), f"Delivered: {item}. We hope you love it."),
            archived=True,
        )
    bank = Address("alerts@northbank.example", "Northbank Alerts")
    merchants = ["ZESTRO", "SHOPKART", "METRO CARD", "ELECTRICITY BOARD", "FITPULSE", "STREAMBOX", "GREENVIEW APTS"]
    for days in sorted(rng.sample(range(1, 75), 12), reverse=True):
        amount = rng.randint(99, 18000)
        merchant = rng.choice(merchants)
        box.single(
            bank,
            ago(days, rng.randint(1, 12)),
            f"₹{amount:,} debited from A/c XX4821",
            f"Dear Customer,\n\n₹{amount:,}.00 has been debited from your account XX4821 at {merchant}.\n\n"
            "Not you? Call 1800-000-0000 immediately.\n\nNorthbank",
            archived=days > 2,
        )
    for service, domain in [("PayWave", "paywave.example"), ("ShopKart", "shopkart.example"), ("Northbank", "northbank.example")] * 3:
        otp(box, service, domain, ago(rng.uniform(1, 70)), rng)

    # Newsletters and promotions
    newsletter(box, "The Morning Byte", "morningbyte.example", "#0f766e", 69, 7, 10, TECH_TOPICS, rng)
    newsletter(box, "Python Digest", "pythondigest.example", "#2563eb", 60, 14, 5, PYTHON_TOPICS, rng)
    newsletter(box, "ShopKart Deals", "deals.shopkart.example", "#f59e0b", 50, 5, 11, DEALS, rng)
    box.single(
        Address("hello@streambox.example", "StreamBox"),
        ago(4, 10),
        "New on StreamBox this week",
        "Three new series and a documentary you'll love. Start watching: https://streambox.example/new",
        _card_html("StreamBox", "New this week", "Three new series and a documentary picked for you.", "https://streambox.example/new", "Watch now", "#dc2626"),
    )

    # Arriving after the demo starts
    box.single(priya, later(2), "Train tickets booked!", "Got all 4 tickets for Friday night, coach B2. Sending the PDF on WhatsApp. Can't wait!", read=False)
    box.single(noreply("Zestro", "zestro.example"), later(7), "Hungry? 40% off your next order", "Use code DEMO40 before midnight.", read=False)

    return box.build()


# ---------------------------------------------------------------- work Outlook


def work_mailbox(owner: Address, anchor: datetime) -> list[RemoteMessage]:
    rng = random.Random("work")
    box = MailboxBuilder("ol", owner, anchor)

    jordan = Address("jordan.blake@northwind.example", "Jordan Blake")
    mei = Address("mei.chen@northwind.example", "Mei Chen")
    ravi = Address("ravi.kumar@northwind.example", "Ravi Kumar")
    people = Address("people@northwind.example", "People Team")
    it = Address("it-help@northwind.example", "IT Helpdesk")
    builds = Address("builds@ci.northwind.example", "Northwind CI")
    tracker = Address("tracker@northwind.example", "Northwind Tracker")
    calendar = Address("calendar@northwind.example", "Calendar")

    box.thread(
        "Q4 roadmap review",
        (jordan, ago(9, 5), "Team, the Q4 roadmap draft is in the shared drive. Please add comments by Thursday. Big themes: sync reliability, search, and the mobile layout."),
        (ravi, ago(9, 3), "Added notes on sync. I think incremental sync needs to land before search, otherwise we index stale data."),
        (None, ago(8, 22), "Agree with Ravi. I've also added an estimate for the provider adapter refactor: about two sprints."),
        (jordan, ago(8, 4), "Thanks both. Let's lock it on Friday's call."),
        starred=True,
    )
    box.thread(
        "Design review: new inbox layout",
        (mei, ago(4, 6), "Sharing the new three-pane inbox mockups. Main changes: account colour chips on each row, and a quieter reading pane.\n\nFigma: https://design.northwind.example/inbox-v2"),
        (None, ago(4, 3), "Love the colour chips. Can we make sure the list still works on a 360px phone screen?"),
        (mei, ago(3, 23), "Good call. Mobile switches to one pane at a time, list first, then the message. Updated the file."),
        (jordan, ago(3, 20), "Looks great. Ship it 🚀"),
    )
    box.thread(
        "Rate limits on the sync service",
        (ravi, ago(2, 7), "We hit the provider's per-user quota again last night during the full resync. Proposal: exponential backoff with jitter, and resume from the last saved cursor instead of starting over."),
        (None, ago(2, 5), "+1. If we commit the cursor after every batch, a crash only replays one batch, and upserts keep that safe."),
        (ravi, ago(1, 22), "Exactly. I'll write it up as a design doc."),
        read=False,
    )
    box.thread(
        "1:1 agenda",
        (jordan, ago(1, 6), "For tomorrow: your growth goals for next quarter, and feedback on the on-call rotation. Anything you'd like to add?"),
        read=False,
    )
    box.single(jordan, ago(16, 4), "Great job on the release", "Just wanted to say the release went really smoothly. Zero rollbacks and great notes. Thank you!", starred=True)
    box.single(people, ago(11, 2), "Open enrollment closes Friday", "Reminder: choose your health plan for next year in the benefits portal before Friday 6 PM.")
    box.single(people, ago(25, 2), "Holiday calendar for next year", "The company holiday calendar is now published on the intranet. Plan your leave early!", archived=True)
    box.single(it, ago(5, 9), "Scheduled maintenance this Saturday", "Email and VPN will be unavailable on Saturday from 01:00 to 03:00 while we upgrade servers.")

    statuses = ["passed", "passed", "failed", "passed", "passed", "failed", "passed", "passed", "passed"]
    for i, status in enumerate(statuses):
        run = 470 + i * 3
        days = 24 - i * 2.6
        detail = "All 214 tests passed." if status == "passed" else "test_sync_resumes_after_crash failed: expected 120 messages, got 100."
        box.single(builds, ago(days, 1), f"Build {status}: main #{run}", f"Pipeline #{run} on main {status}.\n\n{detail}", read=status == "passed" or days > 3, archived=days > 7)
    for i, (key, title) in enumerate([("231", "Sync stalls on large mailboxes"), ("245", "Search ignores accents"), ("252", "Archive shortcut doesn't work on Firefox")]):
        box.thread(
            f"[TRACK-{key}] {title}",
            (tracker, ago(14 - i * 4, 3), f"Jordan Blake assigned TRACK-{key} to you.\n\n{title}\nPriority: High"),
            (tracker, ago(13 - i * 4, 1), f"Ravi Kumar commented on TRACK-{key}: I can reproduce this, logs attached."),
            read=i > 0,
        )
    for week in range(5):
        days = 28 - week * 7
        box.single(calendar, ago(days + 1, 2), "Invitation: Sprint planning (Mon 10:00 - 11:00)", "Jordan Blake invited you to Sprint planning.\nWhere: Room 4B / video call\n\nAccept · Tentative · Decline", archived=days > 7)

    # Work accounts (for the Account Finder)
    welcome(box, "Linkly", "linkly.example", "Build your professional network and discover new roles.", ago(45, 3))
    welcome(box, "CodeNest", "codenest.example", "Host your code, review pull requests and run CI.", ago(38, 6))
    welcome(box, "Notable", "notable.example", "Your notes, synced everywhere.", ago(21, 4), verify=False)
    box.single(
        noreply("CodeNest", "codenest.example"),
        ago(6, 2),
        "New sign-in to your CodeNest account",
        "We noticed a new sign-in from Chrome on Windows (Bengaluru, India).\n\nIf this was you, you can ignore this message.",
    )
    for _ in range(3):
        otp(box, "CodeNest", "codenest.example", ago(rng.uniform(2, 35)), rng)

    box.single(jordan, later(4), "Quick sync before the demo?", "Do you have 10 minutes before the client demo? Want to walk through the sync numbers together.", read=False)

    return box.build()


# ---------------------------------------------------------------- old IMAP account


def legacy_mailbox(owner: Address, anchor: datetime) -> list[RemoteMessage]:
    rng = random.Random("legacy")
    box = MailboxBuilder("im", owner, anchor)

    neha = Address("neha.k@oldmail.example", "Neha Kapoor")

    box.thread(
        "Long time no see!",
        (neha, ago(30, 5), "Alex! Found your old email address while cleaning up my contacts. How have you been? Still coding?"),
        (None, ago(29, 20), "Neha! So good to hear from you. Yes, building an email app these days, ironically. Let's catch up soon!"),
        (neha, ago(29, 2), "Haha perfect. Coffee next week?"),
    )

    # Old accounts made with this address (ShopKart is also on the Gmail address)
    welcome(box, "Chirpr", "chirpr.example", "Share short updates with friends and follow what you love.", ago(340, 4))
    welcome(box, "GameVerse", "gameverse.example", "Your gamer profile is live. Claim your welcome pack!", ago(300, 9))
    welcome(box, "ShopKart", "shopkart.example", "Millions of products, delivered fast.", ago(260, 3))
    welcome(box, "Learnly", "learnly.example", "Learn anything with 10,000+ online courses.", ago(200, 6))
    box.single(
        noreply("Learnly", "learnly.example"),
        ago(150, 2),
        "Your certificate is ready: Python for Beginners",
        "Congratulations on completing Python for Beginners! Download your certificate: https://learnly.example/cert/demo",
        starred=True,
        archived=True,
    )
    box.single(
        noreply("GameVerse", "gameverse.example"),
        ago(90, 5),
        "Reset your GameVerse password",
        "Someone asked to reset your GameVerse password. Use this link within 1 hour: https://gameverse.example/reset?token=demo",
        archived=True,
    )
    box.single(
        noreply("ShopKart", "shopkart.example"),
        ago(120, 4),
        "Your order has shipped",
        "Your order SK-4417820 (USB-C cable, 2 pack) has shipped.",
        archived=True,
    )
    for week in range(8):
        box.single(
            Address("loot@gameverse.example", "GameVerse"),
            ago(56 - week * 7, 3),
            f"Your weekly loot is waiting (week {week + 1})",
            "Log in to claim 500 coins and a mystery chest. Offer ends Sunday.",
            read=week < 6,
            archived=week < 4,
            unsubscribe="<https://gameverse.example/email-preferences?u=demo>",
        )
    for i in range(4):
        box.single(
            Address("updates@chirpr.example", "Chirpr"),
            ago(80 - i * 20, rng.randint(1, 10)),
            f"You have {rng.randint(3, 40)} new notifications",
            "See what your friends have been up to on Chirpr.",
            read=True,
            archived=True,
        )

    # A phishing attempt: a look-alike domain and urgent language. The planned AI triage flags these.
    box.single(
        Address("security@paywave-account-verify.example", "PayWave Security"),
        ago(2, 4),
        "URGENT: Your account will be suspended in 24 hours",
        "Dear user,\n\nWe detected unusual activity. Verify your identity within 24 hours or your account "
        "will be permanently suspended.\n\nVerify now: http://paywave-account-verify.example/login\n\nPayWave Security Team",
        _card_html("PayWave", "Action required", "Verify your identity within 24 hours to avoid suspension.", "http://paywave-account-verify.example/login", "Verify now", "#b91c1c"),
        read=False,
    )

    box.single(Address("loot@gameverse.example", "GameVerse"), later(10), "Double coins weekend starts now", "Log in this weekend to earn double coins on every match.", read=False)

    return box.build()


# The fictional person who owns the three sample mailboxes.
OWNER_NAME = "Alex Morgan"

MAILBOXES = {"gmail": personal_mailbox, "outlook": work_mailbox, "imap": legacy_mailbox}

# The three accounts every demo guest gets: brand, address, display name, colour.
DEMO_ACCOUNTS = [
    ("gmail", "alex.morgan@example.com", "Personal", "#ea4335"),
    ("outlook", "alex.morgan@northwind.example", "Work", "#0078d4"),
    ("imap", "alex_m90@oldmail.example", "Old mail", "#7c3aed"),
]
