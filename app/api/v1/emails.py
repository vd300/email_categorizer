from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.email import Email
from app.schemas.email import (
    DraftReplyRequest,
    DraftReplyResponse,
    EmailImportRequest,
    EmailImportResponse,
    EmailResponse,
    ReprocessResponse,
)
from app.services.ai import EmailAIService
from app.services.email_processor import EmailProcessor, to_email_response

router = APIRouter()


@router.post("/import", response_model=EmailImportResponse)
def import_emails(
    payload: EmailImportRequest,
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
):
    processor = EmailProcessor(db, profile=profile)
    imported = 0
    skipped = 0
    emails: list[EmailResponse] = []
    for item in payload.emails:
        email, duplicate = processor.import_email(item)
        skipped += int(duplicate)
        imported += int(not duplicate)
        if email:
            emails.append(to_email_response(email))
    return EmailImportResponse(imported=imported, skipped_duplicates=skipped, emails=emails)


@router.get("", response_model=list[EmailResponse])
def list_emails(
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
    category: str | None = None,
    urgent: bool | None = None,
    needs_reply: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    query = select(Email).where(Email.profile == profile)
    if category:
        query = query.where(Email.category == category)
    if urgent is not None:
        query = query.where(Email.urgent == urgent)
    if needs_reply is not None:
        query = query.where(Email.needs_reply == needs_reply)
    if search:
        pattern = f"%{search}%"
        query = query.where(Email.subject.ilike(pattern) | Email.body.ilike(pattern))

    query = query.order_by(Email.priority_score.desc(), Email.received_at.desc()).offset(offset).limit(limit)
    return [to_email_response(email) for email in db.scalars(query).all()]


@router.get("/{email_id}", response_model=EmailResponse)
def get_email(
    email_id: int,
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
):
    email = db.scalar(select(Email).where(Email.id == email_id, Email.profile == profile))
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return to_email_response(email)


@router.post("/{email_id}/draft-reply", response_model=DraftReplyResponse)
def draft_reply(
    email_id: int,
    payload: DraftReplyRequest,
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
):
    email = db.scalar(select(Email).where(Email.id == email_id, Email.profile == profile))
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    draft = EmailAIService().draft_reply(
        subject=email.subject,
        sender=email.sender,
        body=email.body,
        tone=payload.tone,
        intent=payload.intent,
    )
    email.draft_reply = draft
    db.commit()
    return DraftReplyResponse(email_id=email.id, draft_reply=draft)


@router.post("/reprocess", response_model=ReprocessResponse)
def reprocess_emails(
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
    limit: int = Query(default=500, ge=1, le=5000),
):
    return ReprocessResponse(processed=EmailProcessor(db, profile=profile).reprocess(limit=limit))
