import os
from types import SimpleNamespace

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.api.v1 import gmail as gmail_api
from app.services.gmail import (
    GmailMessageNotFoundError,
    SCOPES,
    GmailNotConfiguredError,
    GmailService,
    _relaxed_oauth_scope_validation,
)


def test_authorization_url_does_not_include_previously_granted_scopes(monkeypatch):
    captured_kwargs = {}
    service = GmailService(db=SimpleNamespace())

    class FakeFlow:
        code_verifier = "code-verifier"

        def authorization_url(self, **kwargs):
            captured_kwargs.update(kwargs)
            return "https://accounts.example/auth", "oauth-state"

    monkeypatch.setattr(service, "_flow", lambda: FakeFlow())
    monkeypatch.setattr(service, "_store_oauth_state", lambda state, code_verifier: None)

    assert service.authorization_url() == "https://accounts.example/auth"
    assert captured_kwargs == {"access_type": "offline", "prompt": "consent"}


def test_validate_required_scopes_accepts_scope_superset():
    credentials = SimpleNamespace(
        granted_scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            SCOPES[0],
        ],
        scopes=[],
    )

    GmailService._validate_required_scopes(credentials)


def test_validate_required_scopes_rejects_missing_required_scope():
    credentials = SimpleNamespace(
        granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        scopes=[],
    )

    with pytest.raises(GmailNotConfiguredError, match="required scope"):
        GmailService._validate_required_scopes(credentials)


def test_relaxed_oauth_scope_validation_restores_environment(monkeypatch):
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)

    with _relaxed_oauth_scope_validation():
        assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "1"

    assert "OAUTHLIB_RELAX_TOKEN_SCOPE" not in os.environ


def test_apply_labels_translates_missing_gmail_message(monkeypatch):
    service = GmailService(db=SimpleNamespace())

    class FakeModifyRequest:
        def execute(self):
            response = httplib2.Response({"status": "404", "reason": "Not Found"})
            raise HttpError(response, b'{"error": {"message": "not found"}}')

    class FakeMessages:
        def modify(self, **kwargs):
            return FakeModifyRequest()

    class FakeUsers:
        def messages(self):
            return FakeMessages()

    class FakeGmailClient:
        def users(self):
            return FakeUsers()

    monkeypatch.setattr(service, "_gmail_client", lambda: FakeGmailClient())
    monkeypatch.setattr(service, "_ensure_label", lambda client, name: "Label_1")

    with pytest.raises(GmailMessageNotFoundError):
        service.apply_labels_to_message(message_id="missing-id", category="job")


def test_apply_gmail_labels_skips_missing_messages(monkeypatch):
    emails = [
        SimpleNamespace(
            id=1,
            provider_message_id="missing-id",
            category="job",
            urgent=False,
            needs_reply=False,
        ),
        SimpleNamespace(
            id=2,
            provider_message_id="existing-id",
            category="invoice",
            urgent=True,
            needs_reply=False,
        ),
    ]

    class FakeScalars:
        def all(self):
            return emails

    class FakeDb:
        def scalars(self, query):
            return FakeScalars()

    class FakeGmailService:
        def __init__(self, db, profile):
            self.profile = profile

        def apply_labels_to_message(self, message_id, category, urgent, needs_reply):
            if message_id == "missing-id":
                raise GmailMessageNotFoundError()
            return [f"AI Cleaner/{category}", "AI Cleaner/urgent"]

    monkeypatch.setattr(gmail_api, "GmailService", FakeGmailService)

    response = gmail_api.apply_gmail_labels(FakeDb(), profile="alice", limit=200)

    assert response["labeled"] == 1
    assert response["skipped_missing"] == [1]
    assert response["applied_labels"] == {
        "2": ["AI Cleaner/invoice", "AI Cleaner/urgent"]
    }
