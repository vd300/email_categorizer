from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("profile", "provider_message_id", name="uq_emails_profile_provider_message"),
        Index("ix_emails_profile_priority_received", "profile", "priority_score", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile: Mapped[str] = mapped_column(String(120), default="default", index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    sender: Mapped[str] = mapped_column(String(320), index=True)
    recipients: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(String(500), index=True)
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[str] = mapped_column(String(80), index=True, default="uncategorized")
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    needs_reply: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    action_items: Mapped[str] = mapped_column(Text, default="[]")
    labels: Mapped[str] = mapped_column(Text, default="[]")
    draft_reply: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GmailCredential(Base):
    __tablename__ = "gmail_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(120), unique=True, default="default")
    token_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GmailOAuthState(Base):
    __tablename__ = "gmail_oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(120), unique=True, default="default")
    state: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
