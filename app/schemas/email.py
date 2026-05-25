from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmailCategory(StrEnum):
    receipt = "receipt"
    invoice = "invoice"
    payment_due = "payment_due"
    renewal = "renewal"
    job = "job"
    task = "task"
    conversation = "conversation"
    newsletter = "newsletter"
    promotion = "promotion"
    travel = "travel"
    security = "security"
    finance = "finance"
    support = "support"
    other = "other"


class EmailImportItem(BaseModel):
    provider_message_id: str | None = None
    thread_id: str | None = None
    sender: EmailStr | str
    recipients: list[EmailStr | str] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    received_at: datetime | None = None


class EmailImportRequest(BaseModel):
    emails: list[EmailImportItem] = Field(min_length=1, max_length=100)


class EmailAnalysis(BaseModel):
    category: str
    priority_score: float = Field(ge=0, le=100)
    urgent: bool
    needs_reply: bool
    summary: str
    action_items: list[str]
    labels: list[str]


class EmailResponse(BaseModel):
    id: int
    profile: str
    provider_message_id: str | None
    thread_id: str | None
    sender: str
    recipients: list[str]
    subject: str
    body: str
    received_at: datetime | None
    category: str
    priority_score: float
    urgent: bool
    needs_reply: bool
    summary: str
    action_items: list[str]
    labels: list[str]
    draft_reply: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmailImportResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    emails: list[EmailResponse]


class DraftReplyRequest(BaseModel):
    tone: str = Field(default="professional", max_length=80)
    intent: str = Field(default="helpful and concise", max_length=200)


class DraftReplyResponse(BaseModel):
    email_id: int
    draft_reply: str


class CategorySummaryItem(BaseModel):
    category: str
    count: int
    urgent_count: int


class CategorySummaryResponse(BaseModel):
    total: int
    urgent_total: int
    categories: list[CategorySummaryItem]


class ReprocessResponse(BaseModel):
    processed: int
