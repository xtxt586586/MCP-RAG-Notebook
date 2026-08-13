import asyncio

from app.services.llm.deepseek_service import (
    deepseek_service,
)

async def main() -> None:
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个测试助手。"
                "请使用简洁的中文回答问题。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请用一句话解释什么是 RAG。"
            ),
        },
    ]

    answer = await deepseek_service.generate(
        messages=messages,
        temperate=0.2,
    )


    print("DeepSeek 回答：")
    print(answer)

    if not answer.strip():
        raise AssertionError("DeepSeek 返回了空答案")

    print("\nDeepSeek API 测试通过")


if __name__ == "__main__":
    asyncio.run(main())