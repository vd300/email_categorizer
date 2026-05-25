import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import Email
from app.schemas.email import EmailImportItem, EmailResponse
from app.services.ai import EmailAIService


class EmailProcessor:
    def __init__(
        self,
        db: Session,
        ai_service: EmailAIService | None = None,
        profile: str = "default",
    ) -> None:
        self.db = db
        self.ai_service = ai_service or EmailAIService()
        self.profile = profile

    def import_email(self, item: EmailImportItem) -> tuple[Email | None, bool]:
        if item.provider_message_id:
            existing = self.db.scalar(
                select(Email).where(
                    Email.profile == self.profile,
                    Email.provider_message_id == item.provider_message_id,
                )
            )
            if existing:
                return existing, True

        analysis = self.ai_service.analyze(item)
        email = Email(
            profile=self.profile,
            provider_message_id=item.provider_message_id,
            thread_id=item.thread_id,
            sender=str(item.sender),
            recipients=json.dumps([str(recipient) for recipient in item.recipients]),
            subject=item.subject,
            body=item.body,
            received_at=item.received_at,
            category=analysis.category,
            priority_score=analysis.priority_score,
            urgent=analysis.urgent,
            needs_reply=analysis.needs_reply,
            summary=analysis.summary,
            action_items=json.dumps(analysis.action_items),
            labels=json.dumps(analysis.labels),
        )
        self.db.add(email)
        self.db.commit()
        self.db.refresh(email)
        return email, False

    def reprocess(self, limit: int = 500) -> int:
        emails = self.db.scalars(
            select(Email)
            .where(Email.profile == self.profile)
            .order_by(Email.created_at.desc())
            .limit(limit)
        ).all()
        for email in emails:
            item = EmailImportItem(
                provider_message_id=email.provider_message_id,
                thread_id=email.thread_id,
                sender=email.sender,
                recipients=json.loads(email.recipients or "[]"),
                subject=email.subject,
                body=email.body,
                received_at=email.received_at,
            )
            analysis = self.ai_service.analyze(item)
            email.category = analysis.category
            email.priority_score = analysis.priority_score
            email.urgent = analysis.urgent
            email.needs_reply = analysis.needs_reply
            email.summary = analysis.summary
            email.action_items = json.dumps(analysis.action_items)
            email.labels = json.dumps(analysis.labels)
        self.db.commit()
        return len(emails)


def to_email_response(email: Email) -> EmailResponse:
    return EmailResponse(
        id=email.id,
        profile=email.profile,
        provider_message_id=email.provider_message_id,
        thread_id=email.thread_id,
        sender=email.sender,
        recipients=json.loads(email.recipients or "[]"),
        subject=email.subject,
        body=email.body,
        received_at=email.received_at,
        category=email.category,
        priority_score=email.priority_score,
        urgent=email.urgent,
        needs_reply=email.needs_reply,
        summary=email.summary,
        action_items=json.loads(email.action_items or "[]"),
        labels=json.loads(email.labels or "[]"),
        draft_reply=email.draft_reply,
        created_at=email.created_at,
        updated_at=email.updated_at,
    )
