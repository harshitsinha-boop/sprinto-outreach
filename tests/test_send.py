"""SND-03: the recipient is always the owner, dry-run and live share one payload."""

from __future__ import annotations

import inspect
import io
import json

import pytest
import resend
from conftest import CANARY_ENV, FakeSender
from outreach.models import HunterContact
from outreach.send import SendError, build_payload, send_email
from resend.exceptions import ResendError

INTENDED = HunterContact(
    first_name="Richard",
    last_name="Hendricks",
    email="richard@piedpiper.com",
    position="CEO",
    confidence=99,
    source="fixture",
)
HEADER = "DRY RUN - Resend NOT called. Exact payload:\n"


def test_dry_run_prints_payload_and_skips_sender(settings):
    sender = FakeSender()
    buf = io.StringIO()

    result = send_email(
        settings, "Hello", "Body text", dry_run=True, idempotency_key="k1", sender=sender, out=buf
    )

    assert sender.calls == []
    assert result.mode == "dry_run" and result.id is None
    printed = buf.getvalue()
    assert printed.startswith(HEADER)
    assert json.loads(printed[len(HEADER) :]) == result.payload
    assert set(result.payload) == {"from", "to", "subject", "text"}


def test_dry_run_payload_to_is_owner_and_subject_names_intended(settings):
    sender = FakeSender()

    result = send_email(
        settings,
        "Hello",
        "Body",
        dry_run=True,
        idempotency_key="k1",
        intended=INTENDED,
        sender=sender,
        out=io.StringIO(),
    )

    assert result.payload["to"] == ["owner@example.com"]
    assert result.payload["from"] == settings.resend_from
    assert "richard@piedpiper.com" in result.payload["subject"]
    assert "Richard Hendricks" in result.payload["subject"]
    assert result.payload["subject"].endswith("Hello")
    assert "richard@piedpiper.com" not in json.dumps(result.payload["to"])
    assert sender.calls == []


def test_send_email_signature_has_no_to_parameter():
    params = inspect.signature(send_email).parameters
    assert "to" not in params
    assert not [p for p in params if "recipient" in p or p in ("address", "email")]


def test_live_path_passes_identical_payload_and_idempotency_key(settings):
    sender = FakeSender()
    dry = send_email(
        settings, "Subj", "Body", dry_run=True, idempotency_key="k", intended=INTENDED,
        out=io.StringIO(),
    )

    live = send_email(
        settings, "Subj", "Body", dry_run=False, idempotency_key="idem-1", intended=INTENDED,
        sender=sender,
    )

    expected = build_payload(settings, "Subj", "Body", INTENDED)
    assert sender.calls == [(expected, {"idempotency_key": "idem-1"})]
    assert dry.payload == expected == live.payload
    assert live.mode == "sent" and live.id == "fake-msg-123"


def test_live_sets_resend_api_key_at_call_time(settings, monkeypatch):
    monkeypatch.setattr(resend, "api_key", None)

    send_email(settings, "S", "B", dry_run=False, idempotency_key="k", sender=FakeSender())

    assert resend.api_key == CANARY_ENV["RESEND_API_KEY"]


def test_owner_only_403_maps_to_send_error_with_hint(settings):
    message = (
        "You can only send testing emails to your own email address (owner@example.com). "
        f"key={CANARY_ENV['RESEND_API_KEY']}"
    )
    err = ResendError(403, "validation_error", message, "Verify a domain")
    sender = FakeSender(raise_exc=err)

    with pytest.raises(SendError) as excinfo:
        send_email(settings, "S", "B", dry_run=False, idempotency_key="k", sender=sender)

    text = str(excinfo.value)
    assert "OWNER_EMAIL must equal" in text
    assert "403" in text and "validation_error" in text
    for secret in (CANARY_ENV["RESEND_API_KEY"], CANARY_ENV["GEMINI_API_KEY"]):
        assert secret not in text


def test_missing_id_raises_send_error(settings):
    with pytest.raises(SendError):
        send_email(
            settings, "S", "B", dry_run=False, idempotency_key="k", sender=FakeSender(response={})
        )
