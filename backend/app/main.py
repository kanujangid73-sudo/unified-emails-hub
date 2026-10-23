import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import ai, scheduler
from .config import settings
from .database import init_db
from .routers import accounts, attachments, auth, insights, messages, oauth, threads

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.check()
    init_db()
    stop = asyncio.Event()
    background = asyncio.create_task(scheduler.run(stop)) if settings.sync_scheduler else None
    yield
    stop.set()
    if background:
        await background


app = FastAPI(
    title=settings.app_name,
    description="One inbox for every email account: Gmail, Outlook and IMAP adapters, incremental background sync, search, sending, insights and an AI assistant.",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Any local dev server port, outside production.
    allow_origin_regex=None if settings.is_production else r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(oauth.router)
app.include_router(threads.router)
app.include_router(messages.router)
app.include_router(insights.router)
app.include_router(attachments.router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    """For uptime checks and the host's deploy check. Doesn't touch the database, so pinging it
    keeps the API awake without waking a database that sleeps when idle."""
    return {"status": "ok", "version": settings.version, "ai": ai.provider()}


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": settings.app_name, "status": "ok", "docs": "/docs"}
