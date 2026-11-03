"""The only place mail can leave the process (SND-03).

`send_email` has no recipient parameter: the recipient is always the owner, read from
settings inside `build_payload`. A Hunter address may appear only in the subject tag.
Dry-run and live paths share one payload dict, so "prints the exact payload" is true
by construction.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import TextIO

import resend
from resend.exceptions import ResendError

from outreach.config import Settings, redact
from outreach.models import HunterContact, SendResult


class SendError(Exception):
    """Raised when a send is refused or fails. Messages are redacted."""


def build_payload(
    settings: Settings,
    subject: str,
    text: str,
    intended: HunterContact | None = None,
) -> dict:
    if intended is not None:
        name = " ".join(p for p in (intended.first_name, intended.last_name) if p)
        tag = f"[TEST -> {name} <{intended.email}>] "
    else:
        tag = "[TEST] "
    return {
        "from": settings.resend_from,
        "to": [settings.owner_email],
        "subject": tag + subject,
        "text": text,
    }


def send_email(
    settings: Settings,
    subject: str,
    text: str,
    *,
    dry_run: bool,
    idempotency_key: str,
    intended: HunterContact | None = None,
    sender: Callable | None = None,
    out: TextIO | None = None,
) -> SendResult:
    payload = build_payload(settings, subject, text, intended)
    if not settings.owner_email or payload["to"] != [settings.owner_email]:
        raise SendError("refusing to send: recipient is not exactly the owner address")

    if dry_run:
        stream = out if out is not None else sys.stdout
        stream.write("DRY RUN - Resend NOT called. Exact payload:\n")
        stream.write(json.dumps(payload, indent=2) + "\n")
        stream.flush()
        return SendResult(mode="dry_run", payload=payload, id=None)

    # The SDK reads RESEND_API_KEY from the environment at import time; set it at call time.
    resend.api_key = settings.resend_api_key.get_secret_value()
    try:
        resp = (sender or resend.Emails.send)(payload, {"idempotency_key": idempotency_key})
    except ResendError as e:
        # The owner-only 403 arrives as a plain ResendError, not ValidationError.
        detail = f"{e.code} {e.error_type}: {e.message}"
        if e.code == 403 and e.error_type == "validation_error":
            detail += " | OWNER_EMAIL must equal the email address of your Resend account"
        raise SendError(redact(detail, settings)) from None
    message_id = resp.get("id") if resp else None
    if not message_id:
        raise SendError("Resend response had no message id")
    return SendResult(mode="sent", payload=payload, id=message_id)
