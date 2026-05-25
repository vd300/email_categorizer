from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.email import Email
from app.schemas.email import CategorySummaryItem, CategorySummaryResponse

router = APIRouter()


@router.get("/summary", response_model=CategorySummaryResponse)
def category_summary(
    db: Annotated[Session, Depends(get_db)],
    profile: str = Query(default="default", min_length=1, max_length=120),
):
    rows = db.execute(
        select(
            Email.category,
            func.count(Email.id),
            func.sum(case((Email.urgent.is_(True), 1), else_=0)),
        )
        .where(Email.profile == profile)
        .group_by(Email.category)
    ).all()
    total = 0
    urgent_total = 0
    categories: list[CategorySummaryItem] = []
    for category, count, urgent_count in rows:
        urgent_count = int(urgent_count or 0)
        total += int(count)
        urgent_total += urgent_count
        categories.append(
            CategorySummaryItem(category=category, count=int(count), urgent_count=urgent_count)
        )
    return CategorySummaryResponse(total=total, urgent_total=urgent_total, categories=categories)
