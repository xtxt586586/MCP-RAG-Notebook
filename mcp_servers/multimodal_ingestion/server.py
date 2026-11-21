from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from time import perf_counter
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
    "http://127.0.0.1:8765",
).rstrip("/")

SERVER_NAME = "multimodal_ingestion"
REQUEST_TIMEOUT = 180.0
MAX_FILE_SIZE = 20 * 1024 * 1024


SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
}


mcp = FastMCP("MCP-RAG-Notebook Multimodal Ingestion")


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
                    "duration_ms": max(
                        duration_ms,
                        0,
                    ),
                    "arguments": arguments,
                    "result_summary": result_summary,
                    "error_message": error_message,
                },
                headers={
                    "X-MCP-Audit-Token": audit_token,
                },
            )
    except Exception:
        # 审计不可用时不能影响原始工具调用。
        return


def build_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
    }

    access_token = get_access_token()

    if access_token:
        headers["Authorization"] = (
            f"Bearer {access_token}"
        )

    return headers


async def request_json(
    *,
    method: str,
    path: str,
    user_id: str | None,
    tool_name: str,
    audit_arguments: dict[str, Any],
    json_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{BACKEND_URL}{path}"
    started_at = perf_counter()

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
                headers=build_headers(),
            )

        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:1000]

            raise RuntimeError(
                f"后端请求失败：HTTP "
                f"{response.status_code}，{detail}"
            )

        result = response.json()

    except Exception as exc:
        await submit_audit(
            user_id=user_id,
            tool_name=tool_name,
            status="FAILED",
            duration_ms=int(
                (perf_counter() - started_at) * 1000
            ),
            arguments=audit_arguments,
            error_message=str(exc),
        )
        raise

    await submit_audit(
        user_id=user_id,
        tool_name=tool_name,
        status="SUCCESS",
        duration_ms=int(
            (perf_counter() - started_at) * 1000
        ),
        arguments=audit_arguments,
        result_summary=summarize_result(result),
    )

    return result


async def upload_file(
    *,
    user_id: str,
    knowledge_base_id: str,
    file_path: Path,
) -> dict[str, Any]:
    url = f"{BACKEND_URL}/api/v1/documents/upload"
    started_at = perf_counter()

    form_data = {
        "knowledge_base_id": knowledge_base_id,
    }

    mime_type = (
        mimetypes.guess_type(file_path.name)[0]
        or "application/octet-stream"
    )

    files = {
        "file": (
            file_path.name,
            file_path.read_bytes(),
            mime_type,
        )
    }

    audit_arguments = {
        "user_id": user_id,
        "knowledge_base_id": knowledge_base_id,
        "file_name": file_path.name,
        "mime_type": mime_type,
    }

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            trust_env=False,
        ) as client:
            response = await client.post(
                url,
                data=form_data,
                files=files,
                headers=build_headers(),
            )

        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:1000]

            raise RuntimeError(
                f"后端上传失败：HTTP "
                f"{response.status_code}，{detail}"
            )

        result = response.json()

    except Exception as exc:
        await submit_audit(
            user_id=user_id,
            tool_name="ingest_resource",
            status="FAILED",
            duration_ms=int(
                (perf_counter() - started_at) * 1000
            ),
            arguments=audit_arguments,
            error_message=str(exc),
        )
        raise

    await submit_audit(
        user_id=user_id,
        tool_name="ingest_resource",
        status="SUCCESS",
        duration_ms=int(
            (perf_counter() - started_at) * 1000
        ),
        arguments=audit_arguments,
        result_summary=summarize_result(result),
    )

    return result


def validate_uuid(
    value: str,
    field_name: str,
) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} 不能为空"
        )

    try:
        UUID(normalized)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} 必须是合法 UUID"
        ) from exc

    return normalized


def validate_file_path(
    file_path: str,
) -> Path:
    normalized = file_path.strip()

    if not normalized:
        raise ValueError(
            "file_path 不能为空"
        )

    path = Path(normalized).expanduser().resolve()

    if not path.is_file():
        raise ValueError(
            f"文件不存在：{path}"
        )

    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"不支持的文件类型：{extension}"
        )

    file_size = path.stat().st_size

    if file_size <= 0:
        raise ValueError(
            "文件不能为空"
        )

    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            "文件不能超过 20MB"
        )

    return path


@mcp.tool()
async def ingest_resource(
    user_id: str,
    knowledge_base_id: str,
    file_path: str,
) -> dict[str, Any]:
    """
    上传文本、图片、音频或视频资源，
    并交由现有多模态解析和向量化流程处理。
    """
    normalized_user_id = validate_uuid(
        user_id,
        "user_id",
    )

    normalized_knowledge_base_id = validate_uuid(
        knowledge_base_id,
        "knowledge_base_id",
    )

    validated_path = validate_file_path(
        file_path,
    )

    return await upload_file(
        user_id=normalized_user_id,
        knowledge_base_id=(
            normalized_knowledge_base_id
        ),
        file_path=validated_path,
    )


@mcp.tool()
async def get_ingestion_status(
    user_id: str,
    document_id: str,
) -> dict[str, Any]:
    """
    查询文档解析、OCR、ASR、关键帧和向量化任务状态。
    """
    normalized_user_id = validate_uuid(
        user_id,
        "user_id",
    )

    normalized_document_id = validate_uuid(
        document_id,
        "document_id",
    )

    document = await request_json(
        method="GET",
        path=(
            f"/api/v1/documents/"
            f"{normalized_document_id}"
        ),
        user_id=normalized_user_id,
        tool_name="get_ingestion_status",
        audit_arguments={
            "user_id": normalized_user_id,
            "document_id": normalized_document_id,
        },
    )

    task = document.get(
        "ingestion_task"
    ) or {}

    metadata = document.get(
        "metadata"
    ) or {}

    return {
        "document_id": document.get(
            "id",
            normalized_document_id,
        ),
        "file_name": document.get(
            "file_name"
        ),
        "document_status": document.get(
            "status"
        ),
        "task_status": task.get(
            "status"
        ),
        "progress": task.get(
            "progress"
        ),
        "error_message": task.get(
            "error_message"
        ),
        "multimodal_metadata": metadata.get(
            "multimodal",
            {},
        ),
        "celery_task_id": task.get(
            "celery_task_id"
        ),
    }


@mcp.tool()
async def inspect_multimodal_document(
    user_id: str,
    document_id: str,
) -> dict[str, Any]:
    """
    查看文档的解析器、媒体类型、OCR/ASR、
    视频时间线和派生资源信息。
    """
    normalized_user_id = validate_uuid(
        user_id,
        "user_id",
    )

    normalized_document_id = validate_uuid(
        document_id,
        "document_id",
    )

    document = await request_json(
        method="GET",
        path=(
            f"/api/v1/documents/"
            f"{normalized_document_id}"
        ),
        user_id=normalized_user_id,
        tool_name="inspect_multimodal_document",
        audit_arguments={
            "user_id": normalized_user_id,
            "document_id": normalized_document_id,
        },
    )

    metadata = document.get(
        "metadata"
    ) or {}

    return {
        "document_id": document.get(
            "id",
            normalized_document_id,
        ),
        "knowledge_base_id": document.get(
            "knowledge_base_id"
        ),
        "file_name": document.get(
            "file_name"
        ),
        "mime_type": document.get(
            "mime_type"
        ),
        "document_status": document.get(
            "status"
        ),
        "parser": metadata.get(
            "parser"
        ),
        "source_type": metadata.get(
            "source_type"
        ),
        "chunk_count": metadata.get(
            "chunk_count"
        ),
        "multimodal_metadata": metadata.get(
            "multimodal",
            {},
        ),
        "parsed_text_object_name": metadata.get(
            "parsed_text_object_name"
        ),
        "raw_text_object_name": metadata.get(
            "raw_text_object_name"
        ),
        "chunks_object_name": metadata.get(
            "chunks_object_name"
        ),
        "ingestion_task": document.get(
            "ingestion_task"
        ),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
