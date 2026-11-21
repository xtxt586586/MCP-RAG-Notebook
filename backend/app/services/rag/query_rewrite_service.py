import asyncio
import logging

from app.core.config import settings
from app.services.llm.deepseek_service import (
    deepseek_service,
)


logger = logging.getLogger(__name__)


class QueryRewriteService:
    async def rewrite(self, query: str) -> str:
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError("问题不能为空")

        if not settings.rag_query_rewrite_enabled:
            return normalized_query

        messages = [
            {
                "role": "system",
                "content": (
                    "你是知识库检索查询改写器。"
                    "请将用户问题改写成适合向量检索和关键词检索的查询。"
                    "保留原问题中的实体、时间、数字和技术名词。"
                    "只输出一条改写后的查询，不要解释，不要回答问题。"
                ),
            },
            {
                "role": "user",
                "content": normalized_query,
            },
        ]

        try:
            rewritten_query = await asyncio.wait_for(
                deepseek_service.generate(
                    messages=messages,
                    temperature=0.0,
                ),
                timeout=settings.rag_query_rewrite_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "查询改写超时，回退到原始问题 timeout_seconds=%.2f",
                settings.rag_query_rewrite_timeout_seconds,
            )
            return normalized_query
        except Exception:
            logger.warning(
                "查询改写失败，回退到原始问题",
                exc_info=True,
            )
            return normalized_query

        rewritten_query = " ".join(
            rewritten_query.strip().split()
        )

        if not rewritten_query:
            return normalized_query

        if len(rewritten_query) > 500:
            logger.warning(
                "查询改写结果过长，回退到原始问题"
            )
            return normalized_query

        return rewritten_query


query_rewrite_service = QueryRewriteService()
