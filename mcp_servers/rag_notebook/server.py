import mimetypes
import json
import os
from time import perf_counter
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(
    PROJECT_ROOT / ".env",
    override=False,
)

BACKEND_URL = os.getenv(
    "RAG_BACKEND_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

REQUEST_TIMEOUT = 180.0
SERVER_NAME = "rag_notebook"

mcp = FastMCP("MCP-RAG-Notebook")


def get_access_token() -> str:
    load_dotenv(
        PROJECT_ROOT / ".env",
        override=False,
    )

    return os.getenv(
        "RAG_ACCESS_TOKEN",
        "",
    ).strip()


def get_audit_token() -> str:
    load_dotenv(
        PROJECT_ROOT / ".env",
        override=False,
    )

    return os.getenv(
        "MCP_AUDIT_TOKEN",
        "",
    ).strip()


def summarize_result(value: Any) -> str | None:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )[:4000]
    except (TypeError, ValueError):
        return str(value)[:4000]


async def submit_audit(
    *,
    user_id: str | None,
    tool_name: str,
    status: str,
    duration_ms: int,
    arguments: dict[str, Any],
    result_summary: str | None = None,
    error_message: str | None = None,
) -> None:

    audit_token = get_audit_token()

    if not audit_token:
        return

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            trust_env=False,
        ) as client:
            await client.post(
                f"{BACKEND_URL}/api/v1/mcp/audit",
                json={
                    "user_id": user_id,
                    "server_name": SERVER_NAME,
                    "tool_name": tool_name,
                    "status": status,
                    "duration_ms": max(duration_ms, 0),
                    "arguments": arguments,
                    "result_summary": result_summary,
                    "error_message": error_message,
                },
                headers={
                    "X-MCP-Audit-Token": audit_token,
                },
            )
    except Exception:
        return


async def request_json(
    *,
    method: str,
    path: str,
    json_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    tool_name: str | None = None,
    user_id: str | None = None,
    audit_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{BACKEND_URL}{path}"
    started_at = perf_counter()

    headers: dict[str, str] = {}
    access_token = get_access_token()

    if access_token:
        headers["Authorization"] = (
            f"Bearer {access_token}"
        )

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            trust_env=False,
        ) as client:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers,
            )

        if response.is_error:
            try:
                error_detail = response.json()
            except ValueError:
                error_detail = response.text[:1000]

            raise RuntimeError(
                f"后端请求失败：HTTP "
                f"{response.status_code}，"
                f"{error_detail}"
            )

        result = response.json()
    except Exception as exc:
        if tool_name:
            await submit_audit(
                user_id=user_id,
                tool_name=tool_name,
                status="FAILED",
                duration_ms=int(
                    (perf_counter() - started_at) * 1000
                ),
                arguments=audit_arguments or {},
                error_message=str(exc),
            )
        raise

    if tool_name:
        await submit_audit(
            user_id=user_id,
            tool_name=tool_name,
            status="SUCCESS",
            duration_ms=int(
                (perf_counter() - started_at) * 1000
            ),
            arguments=audit_arguments or {},
            result_summary=summarize_result(result),
        )

    return result


async def request_multipart(
    *,
    method: str,
    path: str,
    file_path: Path,
    form_data: dict[str, str],
    tool_name: str | None = None,
    user_id: str | None = None,
    audit_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{BACKEND_URL}{path}"
    started_at = perf_counter()

    headers: dict[str, str] = {}
    access_token = get_access_token()

    if access_token:
        headers["Authorization"] = (
            f"Bearer {access_token}"
        )

    file_data = file_path.read_bytes()

    mime_type = (
        mimetypes.guess_type(file_path.name)[0]
        or "application/octet-stream"
    )

    files = {
        "file": (
            file_path.name,
            file_data,
            mime_type,
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            trust_env=False,
        ) as client:
            response = await client.request(
                method=method,
                url=url,
                data=form_data,
                files=files,
                headers=headers,
            )

        if response.is_error:
            try:
                error_detail = response.json()
            except ValueError:
                error_detail = response.text[:1000]

            raise RuntimeError(
                f"后端请求失败：HTTP "
                f"{response.status_code}，"
                f"{error_detail}"
            )

        result = response.json()
    except Exception as exc:
        if tool_name:
            await submit_audit(
                user_id=user_id,
                tool_name=tool_name,
                status="FAILED",
                duration_ms=int(
                    (perf_counter() - started_at) * 1000
                ),
                arguments=audit_arguments or {},
                error_message=str(exc),
            )
        raise

    if tool_name:
        await submit_audit(
            user_id=user_id,
            tool_name=tool_name,
            status="SUCCESS",
            duration_ms=int(
                (perf_counter() - started_at) * 1000
            ),
            arguments=audit_arguments or {},
            result_summary=summarize_result(result),
        )

    return result


@mcp.tool()
async def backend_health() -> dict[str, Any]:
    return await request_json(
        method="GET",
        path="/health",
        tool_name="backend_health",
    )


@mcp.tool()
async def search_knowledge_base(
    user_id: str,
    knowledge_base_id: str,
    query: str,
    top_k: int = 5,
    mode: str = "hybrid",
) -> dict[str, Any]:
    normalized_query = query.strip()

    if not normalized_query:
        raise ValueError("query 不能为空")

    if not 1 <= top_k <= 20:
        raise ValueError(
            "top_k 必须在 1 到 20 之间"
        )

    if mode not in {
        "dense",
        "sparse",
        "hybrid",
    }:
        raise ValueError(
            "mode 必须是 dense、sparse 或 hybrid"
        )

    return await request_json(
        method="POST",
        path="/api/v1/search",
        json_data={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "query": normalized_query,
            "top_k": top_k,
            "mode": mode,
        },
        tool_name="search_knowledge_base",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "query": normalized_query,
            "top_k": top_k,
            "mode": mode,
        },
    )


@mcp.tool()
async def ask_knowledge_base(
    user_id: str,
    knowledge_base_id: str,
    question: str,
    top_k: int = 5,
) -> dict[str, Any]:
    normalized_question = question.strip()

    if not normalized_question:
        raise ValueError("question 不能为空")

    if not 1 <= top_k <= 20:
        raise ValueError(
            "top_k 必须在 1 到 20 之间"
        )

    return await request_json(
        method="POST",
        path="/api/v1/chat",
        json_data={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "question": normalized_question,
            "top_k": top_k,
        },
        tool_name="ask_knowledge_base",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "question": normalized_question,
            "top_k": top_k,
        },
    )


@mcp.tool(name="search_knowledge")
async def search_knowledge(
    user_id: str,
    knowledge_base_id: str,
    query: str,
    top_k: int = 5,
    mode: str = "hybrid",
) -> dict[str, Any]:
    return await search_knowledge_base(
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        query=query,
        top_k=top_k,
        mode=mode,
    )


@mcp.tool()
async def get_document(
    user_id: str,
    document_id: str,
) -> dict[str, Any]:
    if not user_id.strip():
        raise ValueError("user_id 不能为空")

    try:
        UUID(document_id)
    except ValueError as exc:
        raise ValueError(
            "document_id 必须是合法 UUID"
        ) from exc

    return await request_json(
        method="GET",
        path=f"/api/v1/documents/{document_id}",
        tool_name="get_document",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "document_id": document_id,
        },
    )


@mcp.tool()
async def get_ingestion_status(
    user_id: str,
    document_id: str,
) -> dict[str, Any]:
    document = await request_json(
        method="GET",
        path=f"/api/v1/documents/{document_id}",
        tool_name="get_ingestion_status",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "document_id": document_id,
        },
    )

    task = document.get("ingestion_task") or {}

    return {
        "document_id": document.get(
            "id",
            document_id,
        ),
        "file_name": document.get("file_name"),
        "document_status": document.get("status"),
        "task_status": task.get("status"),
        "progress": task.get("progress"),
        "error_message": task.get(
            "error_message"
        ),
        "celery_task_id": task.get(
            "celery_task_id"
        ),
    }


@mcp.tool()
async def upload_resource(
    user_id: str,
    knowledge_base_id: str,
    file_path: str,
) -> dict[str, Any]:
    if not user_id.strip():
        raise ValueError("user_id 不能为空")

    if not knowledge_base_id.strip():
        raise ValueError(
            "knowledge_base_id 不能为空"
        )

    file_path_object = (
        Path(file_path)
        .expanduser()
        .resolve()
    )

    if not file_path_object.is_file():
        raise ValueError(
            f"文件不存在：{file_path_object}"
        )

    max_file_size = 20 * 1024 * 1024

    if file_path_object.stat().st_size > max_file_size:
        raise ValueError(
            "文件不能超过 20MB"
        )

    return await request_multipart(
        method="POST",
        path="/api/v1/documents/upload",
        file_path=file_path_object,
        form_data={
            "knowledge_base_id": knowledge_base_id,
        },
        tool_name="upload_resource",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "file_name": file_path_object.name,
        },
    )


@mcp.tool()
async def create_note(
    user_id: str,
    knowledge_base_id: str,
    title: str,
    content: str = "",
    source_document_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not user_id.strip():
        raise ValueError("user_id 不能为空")

    if not knowledge_base_id.strip():
        raise ValueError(
            "knowledge_base_id 不能为空"
        )

    try:
        UUID(knowledge_base_id)
    except ValueError as exc:
        raise ValueError(
            "knowledge_base_id 必须是合法 UUID"
        ) from exc

    normalized_title = title.strip()

    if not normalized_title:
        raise ValueError("title 不能为空")

    if len(normalized_title) > 200:
        raise ValueError(
            "title 不能超过 200 个字符"
        )

    normalized_source_document_id = None

    if source_document_id:
        try:
            UUID(source_document_id)
        except ValueError as exc:
            raise ValueError(
                "source_document_id 必须是合法 UUID"
            ) from exc

        normalized_source_document_id = (
            source_document_id
        )

    return await request_json(
        method="POST",
        path="/api/v1/notes",
        json_data={
            "knowledge_base_id": knowledge_base_id,
            "title": normalized_title,
            "content": content,
            "source_document_id": (
                normalized_source_document_id
            ),
            "metadata": metadata or {},
        },
        tool_name="create_note",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "title": normalized_title,
            "content": content,
            "source_document_id": normalized_source_document_id,
            "metadata": metadata or {},
        },
    )


@mcp.tool()
async def search_notes(
    user_id: str,
    knowledge_base_id: str,
    query: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    if not user_id.strip():
        raise ValueError("user_id 不能为空")

    if not knowledge_base_id.strip():
        raise ValueError(
            "knowledge_base_id 不能为空"
        )

    try:
        UUID(knowledge_base_id)
    except ValueError as exc:
        raise ValueError(
            "knowledge_base_id 必须是合法 UUID"
        ) from exc

    if not 1 <= limit <= 100:
        raise ValueError(
            "limit 必须在 1 到 100 之间"
        )

    params: dict[str, Any] = {
        "knowledge_base_id": knowledge_base_id,
        "limit": limit,
    }

    normalized_query = query.strip()

    if normalized_query:
        params["query"] = normalized_query

    return await request_json(
        method="GET",
        path="/api/v1/notes",
        params=params,
        tool_name="search_notes",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "query": normalized_query,
            "limit": limit,
        },
    )


@mcp.tool()
async def summarize_document(
    user_id: str,
    document_id: str,
    max_length: int = 1000,
) -> dict[str, Any]:
    """
    生成指定文档的中文摘要。
    """
    if not user_id.strip():
        raise ValueError("user_id 不能为空")

    try:
        UUID(document_id)
    except ValueError as exc:
        raise ValueError(
            "document_id 必须是合法 UUID"
        ) from exc

    if not 100 <= max_length <= 10000:
        raise ValueError(
            "max_length 必须在 100 到 10000 之间"
        )

    return await request_json(
        method="POST",
        path=(
            f"/api/v1/documents/"
            f"{document_id}/summarize"
        ),
        json_data={
            "max_length": max_length,
        },
        tool_name="summarize_document",
        user_id=user_id,
        audit_arguments={
            "user_id": user_id,
            "document_id": document_id,
            "max_length": max_length,
        },
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
