from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse
from typing import Any, Iterator

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email import GmailCredential, GmailOAuthState
from app.schemas.email import EmailImportItem

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.errors import HttpError
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised in minimal local environments
    Request = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]
    Flow = None  # type: ignore[assignment]
    HttpError = None  # type: ignore[assignment]
    build = None  # type: ignore[assignment]


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
LABEL_PREFIX = "AI Cleaner"


class GmailNotConfiguredError(RuntimeError):
    pass


class GmailNotConnectedError(RuntimeError):
    pass


class GmailMessageNotFoundError(RuntimeError):
    pass


class GmailService:
    def __init__(self, db: Session, profile: str = "default") -> None:
        self.db = db
        self.profile = profile

    def authorization_url(self) -> str:
        flow = self._flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )
        self._store_oauth_state(state=state, code_verifier=flow.code_verifier)
        return auth_url

    def save_callback_credentials(self, authorization_response: str) -> None:
        self._allow_local_http_oauth()
        state = self._state_from_authorization_response(authorization_response)
        oauth_state = self.db.scalar(select(GmailOAuthState).where(GmailOAuthState.state == state))
        if not oauth_state:
            raise GmailNotConfiguredError(
                "OAuth session was not found. Generate a fresh Gmail OAuth URL and try again."
            )

        self.profile = oauth_state.profile
        flow = self._flow(state=oauth_state.state, code_verifier=oauth_state.code_verifier)
        with _relaxed_oauth_scope_validation():
            flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        self._validate_required_scopes(credentials)
        record = self.db.scalar(
            select(GmailCredential).where(GmailCredential.profile == self.profile)
        )
        token_json = credentials.to_json()
        if record:
            record.token_json = token_json
        else:
            self.db.add(GmailCredential(profile=self.profile, token_json=token_json))
        self.db.delete(oauth_state)
        self.db.commit()

    def fetch_recent_messages(self, max_results: int | None = None) -> list[EmailImportItem]:
        service = self._gmail_client()
        result = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results or settings.gmail_sync_max_results)
            .execute()
        )
        messages = result.get("messages", [])
        emails: list[EmailImportItem] = []
        for message in messages:
            payload = (
                service.users()
                .messages()
                .get(userId="me", id=message["id"], format="full")
                .execute()
            )
            emails.append(self._to_import_item(payload))
        return emails

    def apply_labels_to_message(
        self,
        message_id: str,
        category: str,
        urgent: bool = False,
        needs_reply: bool = False,
    ) -> list[str]:
        service = self._gmail_client()
        label_names = [f"{LABEL_PREFIX}/{category}"]
        if urgent:
            label_names.append(f"{LABEL_PREFIX}/urgent")
        if needs_reply:
            label_names.append(f"{LABEL_PREFIX}/needs_reply")

        label_ids = [self._ensure_label(service, name) for name in label_names]
        try:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": label_ids},
            ).execute()
        except HttpError as exc:
            if _is_not_found_error(exc):
                raise GmailMessageNotFoundError(
                    f"Gmail message was not found for id {message_id}."
                ) from exc
            raise
        return label_names

    def _flow(self, state: str | None = None, code_verifier: str | None = None) -> Flow:
        self._allow_local_http_oauth()
        if Flow is None:
            raise GmailNotConfiguredError("Google Gmail SDK packages are not installed.")
        if not settings.google_client_id or not settings.google_client_secret:
            raise GmailNotConfiguredError("Google OAuth credentials are not configured.")

        return Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.google_redirect_uri],
                }
            },
            scopes=SCOPES,
            redirect_uri=settings.google_redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )

    @staticmethod
    def _allow_local_http_oauth() -> None:
        if settings.environment == "local" and settings.allow_insecure_oauth_transport:
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    def _store_oauth_state(self, state: str, code_verifier: str) -> None:
        self.db.execute(delete(GmailOAuthState).where(GmailOAuthState.profile == self.profile))
        self.db.add(
            GmailOAuthState(profile=self.profile, state=state, code_verifier=code_verifier)
        )
        self.db.commit()

    @staticmethod
    def _state_from_authorization_response(authorization_response: str) -> str:
        state = parse_qs(urlparse(authorization_response).query).get("state", [None])[0]
        if not state:
            raise GmailNotConfiguredError(
                "OAuth callback did not include state. Generate a fresh Gmail OAuth URL and try again."
            )
        return state

    def _credentials(self) -> Credentials:
        if Credentials is None or Request is None:
            raise GmailNotConfiguredError("Google Gmail SDK packages are not installed.")

        record = self.db.scalar(select(GmailCredential).where(GmailCredential.profile == self.profile))
        if not record:
            raise GmailNotConnectedError("Gmail is not connected for this profile.")

        credentials = Credentials.from_authorized_user_info(json.loads(record.token_json), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            record.token_json = credentials.to_json()
            self.db.commit()
        return credentials

    def _gmail_client(self) -> Any:
        if build is None:
            raise GmailNotConfiguredError("Google Gmail SDK packages are not installed.")
        return build("gmail", "v1", credentials=self._credentials())

    @staticmethod
    def _validate_required_scopes(credentials: Credentials) -> None:
        effective_scopes = _scope_set(credentials.granted_scopes) or _scope_set(
            credentials.scopes
        )
        missing_scopes = set(SCOPES) - effective_scopes
        if missing_scopes:
            raise GmailNotConfiguredError(
                "Gmail authorization did not grant the required scope(s): "
                f"{', '.join(sorted(missing_scopes))}. Reconnect Gmail and approve access."
            )

    @staticmethod
    def _ensure_label(service: Any, name: str) -> str:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label.get("name") == name:
                return label["id"]

        created = (
            service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created["id"]

    @staticmethod
    def _to_import_item(message: dict[str, Any]) -> EmailImportItem:
        payload = message.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        body = _extract_body(payload) or message.get("snippet", "")
        received_at = None
        if headers.get("date"):
            try:
                received_at = parsedate_to_datetime(headers["date"])
            except (TypeError, ValueError):
                received_at = None

        return EmailImportItem(
            provider_message_id=message.get("id"),
            thread_id=message.get("threadId"),
            sender=headers.get("from", "unknown@example.com"),
            recipients=[headers["to"]] if headers.get("to") else [],
            subject=headers.get("subject", "(no subject)"),
            body=body or "(empty email)",
            received_at=received_at,
        )


def _extract_body(payload: dict[str, Any]) -> str:
    if payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])

    for part in payload.get("parts", []) or []:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain" and part.get("body", {}).get("data"):
            return _decode(part["body"]["data"])
        nested = _extract_body(part)
        if nested:
            return nested
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _scope_set(scopes: Any) -> set[str]:
    if not scopes:
        return set()
    if isinstance(scopes, str):
        return set(scopes.split())
    return set(scopes)


def _is_not_found_error(exc: Any) -> bool:
    return getattr(getattr(exc, "resp", None), "status", None) == 404


@contextmanager
def _relaxed_oauth_scope_validation() -> Iterator[None]:
    previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous
