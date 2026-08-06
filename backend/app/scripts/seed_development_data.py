import asyncio
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.models import KnowledgeBase, User


DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_KNOWLEDGE_BASE_ID = UUID(
    "00000000-0000-0000-0000-000000000101"
)


async def seed_development_data() -> None:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, DEV_USER_ID)

        if user is None:
            user = User(
                id=DEV_USER_ID,
                email="dev@example.com",
                password_hash="development-only-not-a-real-password-hash",
            )

            session.add(user)
            await session.flush()

            print("开发测试用户已创建")
        else:
            print("开发测试用户已存在")

        knowledge_base = await session.get(
            KnowledgeBase,
            DEV_KNOWLEDGE_BASE_ID,
        )

        if knowledge_base is None:
            knowledge_base = KnowledgeBase(
                id=DEV_KNOWLEDGE_BASE_ID,
                user_id=DEV_USER_ID,
                name="开发测试知识库",
                description="用于第三阶段文件上传和 RAG 测试",
            )

            session.add(knowledge_base)

            print("开发测试知识库已创建")
        else:
            print("开发测试知识库已存在")

        await session.commit()

        print("开发测试数据初始化完成")
        print("用户 ID：", DEV_USER_ID)
        print("知识库 ID：", DEV_KNOWLEDGE_BASE_ID)


if __name__ == "__main__":
    asyncio.run(seed_development_data())