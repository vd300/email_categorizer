from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.email import Email
from app.schemas.email import EmailImportResponse
from app.services.email_processor import EmailProcessor, to_email_response
from app.services.gmail import (
    GmailMessageNotFoundError,
    GmailNotConfiguredError,
    GmailNotConnectedError,
    GmailService,
)

router = APIRouter()


@router.get("/oauth/url")
def gmail_oauth_url(
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
):
    try:
        return {"authorization_url": GmailService(db, profile=profile).authorization_url()}
    except GmailNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/callback")
def gmail_oauth_callback(request: Request, db: Annotated[Session, Depends(get_db)]):
    try:
        GmailService(db).save_callback_credentials(str(request.url))
    except GmailNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "connected"}


@router.post("/sync", response_model=EmailImportResponse)
def sync_gmail(
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
):
    try:
        items = GmailService(db, profile=profile).fetch_recent_messages(
            max_results=settings.gmail_sync_max_results
        )
    except GmailNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GmailNotConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    processor = EmailProcessor(db, profile=profile)
    imported = 0
    skipped = 0
    emails = []
    for item in items:
        email, duplicate = processor.import_email(item)
        skipped += int(duplicate)
        imported += int(not duplicate)
        if email:
            emails.append(to_email_response(email))
    return EmailImportResponse(imported=imported, skipped_duplicates=skipped, emails=emails)


@router.post("/apply-labels")
def apply_gmail_labels(
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
    limit: int = 200,
):
    gmail = GmailService(db, profile=profile)
    emails = db.scalars(
        select(Email)
        .where(Email.profile == profile, Email.provider_message_id.is_not(None))
        .order_by(Email.priority_score.desc(), Email.received_at.desc())
        .limit(limit)
    ).all()

    labeled = 0
    applied_labels: dict[str, list[str]] = {}
    skipped_missing: list[int] = []
    try:
        for email in emails:
            try:
                labels = gmail.apply_labels_to_message(
                    message_id=email.provider_message_id or "",
                    category=email.category,
                    urgent=email.urgent,
                    needs_reply=email.needs_reply,
                )
            except GmailMessageNotFoundError:
                skipped_missing.append(email.id)
                continue
            applied_labels[str(email.id)] = labels
            labeled += 1
    except GmailNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GmailNotConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "labeled": labeled,
        "skipped_missing": skipped_missing,
        "message": "Labels were applied in Gmail.",
        "applied_labels": applied_labels,
    }
