from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.email import EmailAnalysis, EmailImportItem

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised in minimal local environments
    OpenAI = None  # type: ignore[assignment]


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "payment_due": ("due", "overdue", "pay now", "payment reminder", "late fee"),
    "invoice": ("invoice", "bill", "statement"),
    "receipt": ("receipt", "order confirmation", "payment received", "tax invoice"),
    "renewal": ("renew", "renewal", "subscription", "expires", "expiry"),
    "job": ("job", "career", "interview", "recruiter", "application", "hiring", "opportunity"),
    "task": ("action required", "please review", "todo", "to-do", "deadline", "assignment"),
    "travel": ("flight", "hotel", "booking", "itinerary", "reservation", "boarding"),
    "security": ("security alert", "password", "login", "verification", "2fa", "otp"),
    "finance": ("bank", "credit card", "mutual fund", "loan", "emi", "transaction"),
    "support": ("ticket", "support", "case", "request received"),
    "newsletter": ("newsletter", "digest", "weekly update"),
    "promotion": ("sale", "discount", "offer", "coupon", "deal"),
    "conversation": ("re:", "fwd:", "following up", "checking in"),
}

URGENT_KEYWORDS = (
    "urgent",
    "asap",
    "immediately",
    "today",
    "tomorrow",
    "overdue",
    "final notice",
    "deadline",
    "expires",
    "action required",
    "payment due",
)

REPLY_KEYWORDS = (
    "can you",
    "could you",
    "please confirm",
    "please review",
    "let me know",
    "reply",
    "respond",
    "?",
)


@dataclass(frozen=True)
class EmailAIService:
    """Uses OpenAI when configured, otherwise falls back to explainable heuristics."""

    def analyze(self, email: EmailImportItem) -> EmailAnalysis:
        if settings.openai_api_key:
            try:
                return self._analyze_with_openai(email)
            except Exception:
                return self._analyze_with_rules(email)
        return self._analyze_with_rules(email)

    def draft_reply(self, subject: str, sender: str, body: str, tone: str, intent: str) -> str:
        if settings.openai_api_key:
            try:
                return self._draft_with_openai(subject, sender, body, tone, intent)
            except Exception:
                pass

        return self._draft_with_rules(subject)

    @staticmethod
    def _draft_with_rules(subject: str) -> str:
        return (
            f"Hi,\n\nThanks for your email about \"{subject}\". "
            f"I have reviewed it and will follow up on the required next steps. "
            f"Please let me know if there is any additional context I should consider.\n\nBest regards"
        )

    def _analyze_with_openai(self, email: EmailImportItem) -> EmailAnalysis:
        if OpenAI is None:
            return self._analyze_with_rules(email)

        client = OpenAI(api_key=settings.openai_api_key)
        prompt = {
            "sender": str(email.sender),
            "subject": email.subject,
            "body": email.body[:12000],
            "allowed_categories": list(CATEGORY_KEYWORDS.keys()) + ["other"],
        }
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify and prioritize this email. Return strict JSON with keys: "
                        "category, priority_score, urgent, needs_reply, summary, action_items, labels. "
                        "priority_score must be 0-100. action_items and labels must be arrays."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            return EmailAnalysis.model_validate_json(content)
        except ValidationError:
            return EmailAnalysis.model_validate(json.loads(content))

    def _draft_with_openai(
        self, subject: str, sender: str, body: str, tone: str, intent: str
    ) -> str:
        if OpenAI is None:
            return self._draft_with_rules(subject)

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": "Draft a concise email reply. Do not invent facts or commitments.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "sender": sender,
                            "subject": subject,
                            "email_body": body[:12000],
                            "tone": tone,
                            "intent": intent,
                        }
                    ),
                },
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def _analyze_with_rules(self, email: EmailImportItem) -> EmailAnalysis:
        text = f"{email.subject}\n{email.body}".lower()
        category = self._classify(text)
        urgent = any(word in text for word in URGENT_KEYWORDS)
        needs_reply = any(word in text for word in REPLY_KEYWORDS)
        action_items = self._extract_action_items(email.body)
        labels = self._labels_for(text, category, urgent, needs_reply)
        score = self._priority_score(text, category, urgent, needs_reply, action_items)

        return EmailAnalysis(
            category=category,
            priority_score=score,
            urgent=urgent,
            needs_reply=needs_reply,
            summary=self._summarize(email.subject, email.body),
            action_items=action_items,
            labels=labels,
        )

    @staticmethod
    def _classify(text: str) -> str:
        scores = {
            category: sum(1 for keyword in keywords if keyword in text)
            for category, keywords in CATEGORY_KEYWORDS.items()
        }
        best_category, best_score = max(scores.items(), key=lambda item: item[1])
        return best_category if best_score > 0 else "other"

    @staticmethod
    def _priority_score(
        text: str, category: str, urgent: bool, needs_reply: bool, action_items: list[str]
    ) -> float:
        score = 20.0
        if category in {"payment_due", "invoice", "security", "task"}:
            score += 25
        if category in {"job", "renewal", "finance"}:
            score += 15
        if urgent:
            score += 30
        if needs_reply:
            score += 15
        if action_items:
            score += min(len(action_items) * 7, 20)
        if any(amount in text for amount in ("$", "₹", "rs.", "inr", "usd")):
            score += 5
        return min(round(score, 2), 100.0)

    @staticmethod
    def _summarize(subject: str, body: str) -> str:
        clean_body = re.sub(r"\s+", " ", body).strip()
        first_sentence = re.split(r"(?<=[.!?])\s+", clean_body)[0] if clean_body else ""
        summary = first_sentence[:220].strip()
        if len(first_sentence) > 220:
            summary += "..."
        return summary or subject

    @staticmethod
    def _extract_action_items(body: str) -> list[str]:
        patterns = (
            r"(?i)(?:please|kindly)\s+([^.!?\n]{8,160})",
            r"(?i)(?:action required|todo|to-do|deadline):?\s*([^.!?\n]{8,160})",
            r"(?i)(?:pay|renew|submit|review|confirm|schedule)\s+([^.!?\n]{8,160})",
        )
        items: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, body):
                item = re.sub(r"\s+", " ", match).strip(" .:-")
                if item and item.lower() not in {existing.lower() for existing in items}:
                    items.append(item)
                if len(items) >= 5:
                    return items
        return items

    @staticmethod
    def _labels_for(text: str, category: str, urgent: bool, needs_reply: bool) -> list[str]:
        labels = [category]
        if urgent:
            labels.append("urgent")
        if needs_reply:
            labels.append("needs_reply")
        if any(token in text for token in ("due", "deadline", "expires")):
            labels.append("deadline")
        return labels
