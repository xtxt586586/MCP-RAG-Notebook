import asyncio
import json
import sys
import time

import httpx


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


STREAM_URL = (
    "http://127.0.0.1:8000"
    "/api/v1/chat/stream"
)


async def main() -> None:
    request_data = {
        "user_id": (
            "00000000-0000-0000-"
            "0000-000000000001"
        ),
        "knowledge_base_id": (
            "00000000-0000-0000-"
            "0000-000000000101"
        ),
        "question": (
            "LangChain 在资料中"
            "解决了什么问题？"
        ),
        "top_k": 2,
    }

    sources: list[dict] = []
    answer_parts: list[str] = []

    received_done = False
    received_error = False

    start_time = time.perf_counter()
    first_token_time: float | None = None

    current_event: str | None = None

    async with httpx.AsyncClient(
        timeout=180,
    ) as client:
        async with client.stream(
            "POST",
            STREAM_URL,
            json=request_data,
        ) as response:
            print(
                "HTTP 状态码：",
                response.status_code,
            )

            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    current_event = (
                        line[6:].strip()
                    )
                    continue

                if not line.startswith("data:"):
                    continue

                data_text = line[5:].strip()
                data = json.loads(data_text)

                if current_event == "sources":
                    sources = data.get(
                        "sources",
                        [],
                    )

                    print("\n引用来源：")

                    for source in sources:
                        print(
                            source["citation"],
                            source["file_name"],
                        )

                elif current_event == "token":
                    content = data.get(
                        "content",
                        "",
                    )

                    if (
                        content
                        and first_token_time is None
                    ):
                        first_token_time = (
                            time.perf_counter()
                            - start_time
                        )

                    answer_parts.append(content)

                    print(
                        content,
                        end="",
                        flush=True,
                    )

                elif current_event == "done":
                    received_done = True

                elif current_event == "error":
                    received_error = True

                    print(
                        "\n流式错误：",
                        data.get("message"),
                    )

    total_time = (
        time.perf_counter()
        - start_time
    )

    complete_answer = "".join(answer_parts)

    print("\n\n完整回答：")
    print(complete_answer)

    print("\n性能信息：")
    print(
        "首个回答片段耗时：",
        first_token_time,
    )
    print(
        "总耗时：",
        round(total_time, 2),
        "秒",
    )
    print(
        "回答片段数量：",
        len(answer_parts),
    )

    if received_error:
        raise AssertionError(
            "服务端返回了 error 事件"
        )

    if not received_done:
        raise AssertionError(
            "没有收到 done 事件"
        )

    if not complete_answer.strip():
        raise AssertionError(
            "流式回答为空"
        )

    if not sources:
        raise AssertionError(
            "没有收到引用来源"
        )

    has_citation = any(
        source["citation"]
        in complete_answer
        for source in sources
    )

    if not has_citation:
        raise AssertionError(
            "回答中没有引用标记"
        )

    print("\n3E-D 流式问答测试通过")


if __name__ == "__main__":
    asyncio.run(main())