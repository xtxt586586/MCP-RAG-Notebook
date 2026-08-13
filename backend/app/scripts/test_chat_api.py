import asyncio
import json
import sys

import httpx


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


CHAT_URL = (
    "http://127.0.0.1:8000"
    "/api/v1/chat"
)

USER_ID = (
    "00000000-0000-0000-0000-000000000001"
)

KNOWLEDGE_BASE_ID = (
    "00000000-0000-0000-0000-000000000101"
)


async def main() -> None:
    request_data = {
        "user_id": USER_ID,
        "knowledge_base_id": KNOWLEDGE_BASE_ID,
        "question": (
            "LangChain 在资料中"
            "解决了什么问题？"
        ),
        "top_k": 2,
    }

    async with httpx.AsyncClient(
        timeout=180,
    ) as client:
        response = await client.post(
            CHAT_URL,
            json=request_data,
        )

        print("正常问答状态码：")
        print(response.status_code)

        response.raise_for_status()

        result = response.json()

        print("\nRAG 接口响应：")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not result["answer"].strip():
            raise AssertionError(
                "接口返回的回答为空"
            )

        if not result["sources"]:
            raise AssertionError(
                "接口没有返回引用来源"
            )

        has_citation = any(
            source["citation"]
            in result["answer"]
            for source in result["sources"]
        )

        if not has_citation:
            raise AssertionError(
                "回答中没有引用标记"
            )

        wrong_user_response = await client.post(
            CHAT_URL,
            json={
                **request_data,
                "user_id": (
                    "00000000-0000-0000-"
                    "0000-000000000002"
                ),
            },
        )

        print(
            "\n错误用户状态码：",
            wrong_user_response.status_code,
        )

        if wrong_user_response.status_code != 404:
            raise AssertionError(
                "用户和知识库隔离测试失败"
            )

        empty_question_response = (
            await client.post(
                CHAT_URL,
                json={
                    **request_data,
                    "question": "   ",
                },
            )
        )

        print(
            "空问题状态码：",
            empty_question_response.status_code,
        )

        if (
            empty_question_response.status_code
            != 422
        ):
            raise AssertionError(
                "空问题校验失败"
            )

        invalid_top_k_response = (
            await client.post(
                CHAT_URL,
                json={
                    **request_data,
                    "top_k": 21,
                },
            )
        )

        print(
            "错误 top_k 状态码：",
            invalid_top_k_response.status_code,
        )

        if (
            invalid_top_k_response.status_code
            != 422
        ):
            raise AssertionError(
                "top_k 范围校验失败"
            )

    print("\n3E-C RAG 接口测试通过")


if __name__ == "__main__":
    asyncio.run(main())