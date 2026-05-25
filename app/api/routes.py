from fastapi import APIRouter

from app.api.v1 import categories, emails, gmail

router = APIRouter()
router.include_router(emails.router, prefix="/emails", tags=["emails"])
router.include_router(categories.router, prefix="/categories", tags=["categories"])
router.include_router(gmail.router, prefix="/gmail", tags=["gmail"])
