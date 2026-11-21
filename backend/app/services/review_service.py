import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.models import Note, ReviewEvent, ReviewRecord
from app.services.llm.deepseek_service import deepseek_service


REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]


def get_next_interval(review_count: int) -> int:
    index = min(
        max(review_count, 0),
        len(REVIEW_INTERVALS) - 1,
    )
    return REVIEW_INTERVALS[index]


class ReviewService:
    async def get_stats(
        self,
        *,
        user_id: UUID,
    ) -> dict[str, Any]:
        """Return review progress derived from the per-note review records.

        The current schema stores the aggregate count and the latest review
        timestamp for each note, rather than one row per review event.  The
        recent activity value therefore counts notes reviewed in the window,
        not individual attempts.
        """
        from app.core.database import AsyncSessionLocal

        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=7)

        async with AsyncSessionLocal() as db:
            total_notes = await db.scalar(
                select(func.count(Note.id)).where(
                    Note.user_id == user_id,
                )
            )

            record_stats = await db.execute(
                select(
                    func.count(ReviewRecord.id),
                    func.count(ReviewRecord.id).filter(
                        ReviewRecord.review_count > 0,
                    ),
                    func.coalesce(
                        func.sum(ReviewRecord.review_count),
                        0,
                    ),
                    func.count(ReviewRecord.id).filter(
                        ReviewRecord.next_review_at <= now,
                    ),
                    func.count(ReviewRecord.id).filter(
                        ReviewRecord.last_reviewed_at >= recent_cutoff,
                    ),
                    func.max(ReviewRecord.last_reviewed_at),
                    func.min(ReviewRecord.next_review_at).filter(
                        ReviewRecord.next_review_at > now,
                    ),
                ).where(ReviewRecord.user_id == user_id)
            )

            (
                tracked_notes,
                reviewed_notes,
                total_review_count,
                due_count,
                recent_reviewed_notes,
                last_reviewed_at,
                next_review_at,
            ) = record_stats.one()

            event_stats = await db.execute(
                select(
                    func.count(ReviewEvent.id),
                    func.count(func.distinct(ReviewEvent.note_id)),
                ).where(
                    ReviewEvent.user_id == user_id,
                    ReviewEvent.reviewed_at >= recent_cutoff,
                )
            )
            recent_review_count, recent_event_notes = event_stats.one()

        return {
            "total_notes": int(total_notes or 0),
            "tracked_notes": int(tracked_notes or 0),
            "reviewed_notes": int(reviewed_notes or 0),
            "due_count": int(due_count or 0),
            "total_review_count": int(total_review_count or 0),
            "recent_reviewed_notes": int(
                recent_event_notes
                if recent_event_notes is not None
                else recent_reviewed_notes or 0
            ),
            "recent_review_count": int(recent_review_count or 0),
            "last_reviewed_at": (
                last_reviewed_at.isoformat()
                if last_reviewed_at
                else None
            ),
            "next_review_at": (
                next_review_at.isoformat()
                if next_review_at
                else None
            ),
        }

    async def get_history(
        self,
        *,
        user_id: UUID,
        days: int = 30,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        from app.core.database import AsyncSessionLocal

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ReviewEvent, Note)
                .join(Note, Note.id == ReviewEvent.note_id)
                .where(
                    ReviewEvent.user_id == user_id,
                    Note.user_id == user_id,
                    ReviewEvent.reviewed_at >= cutoff,
                )
                .order_by(ReviewEvent.reviewed_at.desc())
                .limit(limit)
            )
            rows = result.all()

        return [
            {
                "event_id": str(event.id),
                "note_id": str(note.id),
                "title": note.title,
                "review_count": event.review_count,
                "interval_days": event.interval_days,
                "reviewed_at": event.reviewed_at.isoformat(),
            }
            for event, note in rows
        ]

    async def get_trend(
        self,
        *,
        user_id: UUID,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        from app.core.database import AsyncSessionLocal

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        review_day = func.date(ReviewEvent.reviewed_at)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    review_day.label("review_day"),
                    func.count(ReviewEvent.id).label("count"),
                )
                .where(
                    ReviewEvent.user_id == user_id,
                    ReviewEvent.reviewed_at >= cutoff,
                )
                .group_by(review_day)
                .order_by(review_day.asc())
            )
            rows = result.all()

        return [
            {
                "date": str(review_day_value),
                "count": int(count),
            }
            for review_day_value, count in rows
        ]

    async def get_today_reviews(
        self,
        *,
        user_id: UUID,
    ) -> list[dict[str, Any]]:
        from app.core.database import AsyncSessionLocal

        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ReviewRecord, Note)
                .join(Note, Note.id == ReviewRecord.note_id)
                .where(
                    ReviewRecord.user_id == user_id,
                    Note.user_id == user_id,
                    ReviewRecord.next_review_at <= now,
                )
                .order_by(
                    ReviewRecord.next_review_at.asc()
                )
            )

            rows = result.all()

        return [
            {
                "review_id": str(record.id),
                "note_id": str(note.id),
                "title": note.title,
                "content_preview": note.content[:240],
                "review_count": record.review_count,
                "last_reviewed_at": (
                    record.last_reviewed_at.isoformat()
                    if record.last_reviewed_at
                    else None
                ),
                "interval_days": record.interval_days,
            }
            for record, note in rows
        ]

    async def mark_reviewed(
        self,
        *,
        note_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ReviewRecord).where(
                    ReviewRecord.note_id == note_id,
                    ReviewRecord.user_id == user_id,
                )
            )

            record = result.scalar_one_or_none()

            if record is None:
                return {
                    "success": False,
                    "message": "回顾记录不存在",
                }

            now = datetime.now(timezone.utc)
            review_count = record.review_count + 1
            interval_days = get_next_interval(review_count)

            record.review_count = review_count
            record.interval_days = interval_days
            record.last_reviewed_at = now
            record.next_review_at = (
                now + timedelta(days=interval_days)
            )

            db.add(
                ReviewEvent(
                    note_id=note_id,
                    user_id=user_id,
                    review_count=review_count,
                    interval_days=interval_days,
                    reviewed_at=now,
                )
            )

            await db.commit()

            return {
                "success": True,
                "message": "已完成回顾",
                "review_count": review_count,
                "interval_days": interval_days,
                "next_review_at": record.next_review_at.isoformat(),
            }

    async def get_question(
        self,
        *,
        note_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Note).where(
                    Note.id == note_id,
                    Note.user_id == user_id,
                )
            )

            note = result.scalar_one_or_none()

        if note is None:
            return {
                "question": "笔记不存在",
                "choices": [],
                "answer": "",
            }

        return await self.generate_question(note.content)

    async def generate_question(
        self,
        content: str,
    ) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个专业的笔记回顾助手。"
                    "请根据笔记内容生成一道四选一选择题。"
                    "只输出 JSON，不要输出解释。"
                ),
            },
            {
                "role": "user",
                "content": f"""
笔记内容：
{content[:3000]}

输出格式：
{{
  "question": "问题",
  "choices": ["选项A", "选项B", "选项C", "选项D"],
  "answer": "正确选项的完整文本"
}}
""",
            },
        ]

        try:
            raw = await deepseek_service.generate(
                messages=messages,
                temperature=0.1,
            )

            raw = raw.strip()

            if "```" in raw:
                raw = raw.replace("```json", "")
                raw = raw.replace("```", "")

            start = raw.find("{")
            end = raw.rfind("}")

            if start >= 0 and end > start:
                raw = raw[start : end + 1]

            data = json.loads(raw)

            choices = data.get("choices", [])
            answer = data.get("answer", "")

            if (
                not isinstance(data.get("question"), str)
                or not isinstance(choices, list)
                or len(choices) != 4
                or answer not in choices
            ):
                raise ValueError("回顾题目格式无效")

            return {
                "question": data["question"],
                "choices": choices,
                "answer": answer,
            }

        except Exception:
            return {
                "question": "这篇笔记的核心内容是什么？",
                "choices": [
                    "需要重新阅读后判断",
                    "笔记中没有明确说明",
                    "以上内容均不相关",
                    "需要结合笔记正文回答",
                ],
                "answer": "需要结合笔记正文回答",
            }


review_service = ReviewService()
