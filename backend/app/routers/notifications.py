"""Public CASL email unsubscribe / re-subscribe endpoints.

A one-click link in email footers points at GET /api/notifications/unsubscribe.
To avoid mail-client link prefetchers silently unsubscribing people, the GET
only renders a confirmation page; the actual opt-out happens on the POST that
the page's button submits. Re-subscribing works the same way.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

unsubscribe_rate_limit = rate_limit_dependency("unsubscribe", settings.AUTH_RATE_LIMIT_MAX_REQUESTS)

_APP_URL = settings.APP_BASE_URL.rstrip("/")


def _user_for_token(db: Session, token: str) -> Optional[User]:
    try:
        token_uuid = UUID(str(token))
    except (ValueError, AttributeError, TypeError):
        return None
    return db.query(User).filter(User.unsubscribe_token == token_uuid).first()


def _page(title: str, body_html: str) -> HTMLResponse:
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title></head>
<body style="margin:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <div style="max-width:520px;margin:48px auto;background:#fff;border-radius:10px;padding:32px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <p style="margin:0 0 16px;color:#00263E;font-size:18px;font-weight:700;">BIPOC Foundation Hub</p>
    {body_html}
  </div>
</body></html>"""
    return HTMLResponse(content=html)


def _button_form(action: str, token: str, label: str) -> str:
    return (
        f'<form method="post" action="{action}" style="margin:20px 0 0;">'
        f'<input type="hidden" name="token" value="{token}" />'
        f'<button type="submit" style="display:inline-block;padding:12px 24px;background:#C8102E;'
        f'color:#fff;border:none;border-radius:6px;font-weight:600;font-size:14px;cursor:pointer;">'
        f'{label}</button></form>'
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_landing(
    token: str = Query(...),
    db: Session = Depends(get_db),
    _: None = Depends(unsubscribe_rate_limit),
):
    user = _user_for_token(db, token)
    if not user:
        return _page(
            "Unsubscribe",
            '<p style="color:#444;font-size:15px;line-height:1.6;">This unsubscribe link is '
            'invalid or has expired. If you keep receiving unwanted email, contact us and we '
            'will remove you.</p>',
        )
    if not user.opt_in_email:
        return _page(
            "Already unsubscribed",
            '<p style="color:#444;font-size:15px;line-height:1.6;">You are already unsubscribed '
            'from non-essential email. You will still receive essential messages about your '
            'bookings and account.</p>'
            + _button_form(f"{_APP_URL}/api/notifications/resubscribe", token, "Re-subscribe"),
        )
    return _page(
        "Confirm unsubscribe",
        f'<p style="color:#444;font-size:15px;line-height:1.6;">Unsubscribe '
        f'<strong>{user.email}</strong> from non-essential email? You will still receive '
        f'essential messages about your bookings and account.</p>'
        + _button_form(f"{_APP_URL}/api/notifications/unsubscribe", token, "Unsubscribe"),
    )


@router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirm(
    token: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(unsubscribe_rate_limit),
):
    user = _user_for_token(db, token)
    if not user:
        return _page(
            "Unsubscribe",
            '<p style="color:#444;font-size:15px;line-height:1.6;">This unsubscribe link is '
            'invalid or has expired.</p>',
        )
    user.opt_in_email = False
    db.commit()
    return _page(
        "Unsubscribed",
        '<p style="color:#444;font-size:15px;line-height:1.6;">You have been unsubscribed from '
        'non-essential email. You will still receive essential messages about your bookings and '
        'account. Changed your mind?</p>'
        + _button_form(f"{_APP_URL}/api/notifications/resubscribe", token, "Re-subscribe"),
    )


@router.post("/resubscribe", response_class=HTMLResponse)
def resubscribe(
    token: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(unsubscribe_rate_limit),
):
    user = _user_for_token(db, token)
    if not user:
        return _page(
            "Re-subscribe",
            '<p style="color:#444;font-size:15px;line-height:1.6;">This link is invalid or has '
            'expired.</p>',
        )
    user.opt_in_email = True
    db.commit()
    return _page(
        "Re-subscribed",
        '<p style="color:#444;font-size:15px;line-height:1.6;">You are subscribed again and will '
        'receive email from us.</p>',
    )
