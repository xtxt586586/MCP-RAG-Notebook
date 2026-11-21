from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser
from app.services.review_service import review_service


router = APIRouter(
    prefix="/reviews",
    tags=["每日回顾"],
)


@router.get("/today")
async def get_today_reviews(
    current_user: CurrentUser,
) -> dict:
    reviews = await review_service.get_today_reviews(
        user_id=current_user.id,
    )

    return {
        "reviews": reviews,
        "total_count": len(reviews),
    }


@router.get("/stats")
async def get_review_stats(
    current_user: CurrentUser,
) -> dict:
    return await review_service.get_stats(
        user_id=current_user.id,
    )


@router.get("/history")
async def get_review_history(
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    events = await review_service.get_history(
        user_id=current_user.id,
        days=days,
        limit=limit,
    )
    daily_counts = await review_service.get_trend(
        user_id=current_user.id,
        days=days,
    )
    return {
        "events": events,
        "daily_counts": daily_counts,
        "days": days,
        "total_count": len(events),
    }


@router.post("/done/{note_id}")
async def mark_reviewed(
    note_id: UUID,
    current_user: CurrentUser,
) -> dict:
    return await review_service.mark_reviewed(
        note_id=note_id,
        user_id=current_user.id,
    )


@router.get("/question/{note_id}")
async def get_review_question(
    note_id: UUID,
    current_user: CurrentUser,
) -> dict:
    return await review_service.get_question(
        note_id=note_id,
        user_id=current_user.id,
    )
