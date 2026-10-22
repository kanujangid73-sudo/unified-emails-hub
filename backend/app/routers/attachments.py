from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from ..database import get_session
from ..models import Attachment, MailAccount, Message, User
from ..providers import AuthError, ProviderError, get_provider
from ..security import get_current_user

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

# Types a browser would render or run if opened directly. They're always served as a plain
# download, so an attachment can never execute script on the app's origin.
ACTIVE_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/xml",
    "application/xml",
    "text/javascript",
    "application/javascript",
}
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024


def safe_type(mime_type: str) -> str:
    mime_type = (mime_type or "").split(";")[0].strip().lower()
    if not mime_type or "/" not in mime_type or mime_type in ACTIVE_TYPES:
        return "application/octet-stream"
    return mime_type


def content_disposition(filename: str) -> str:
    # An ASCII fallback plus the exact UTF-8 name (RFC 6266 / 5987), with no quotes or line breaks.
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename) or "attachment"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("/{attachment_id}")
def download(attachment_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> Response:
    """Download an attachment. Its content is fetched from the mail provider at this moment."""
    attachment = session.get(Attachment, attachment_id)
    message = session.get(Message, attachment.message_id) if attachment else None
    account = session.get(MailAccount, message.account_id) if message else None
    if account is None or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")

    if attachment.data is not None:
        content = attachment.data
    else:
        try:
            content = get_provider(account).fetch_attachment(message.remote_id, attachment.ref)
        except AuthError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        except ProviderError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise HTTPException(413, "This attachment is too large to download here. Open it in your mail app.")
    return Response(
        content,
        media_type=safe_type(attachment.mime_type),
        headers={
            "Content-Disposition": content_disposition(attachment.filename),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )
