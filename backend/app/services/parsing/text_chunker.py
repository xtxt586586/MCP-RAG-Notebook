from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
)

from app.services.parsing.document_parser import ParsedUnit


CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


def create_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=[
            "\n\n",
            "\n",
            "。",
            "！",
            "？",
            "；",
            "，",
            " ",
            "",
        ],
    )


def create_chunks(
    parsed_units: list[ParsedUnit],
    *,
    user_id: str,
    knowledge_base_id: str,
    document_id: str,
    file_name: str,
    source_type: str,
) -> list[dict]:
    splitter = create_text_splitter()

    chunks: list[dict] = []
    chunk_index = 0

    for parsed_unit in parsed_units:
        texts = splitter.split_text(parsed_unit.text)

        for text in texts:
            text = text.strip()

            if not text:
                continue

            start_seconds = float(
                parsed_unit.metadata.get(
                    "start_seconds",
                    -1.0,
                )
            )

            end_seconds = float(
                parsed_unit.metadata.get(
                    "end_seconds",
                    -1.0,
                )
            )

            chunks.append(
                {
                    "id": f"{document_id}:{chunk_index}",
                    "user_id": user_id,
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": document_id,
                    "chunk_index": chunk_index,
                    "content": text,
                    "source_type": source_type,
                    "page_number": parsed_unit.page_number,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "metadata": {
                        "file_name": file_name,
                        **parsed_unit.metadata,
                    },
                }
            )

            chunk_index += 1

    if not chunks:
        raise ValueError("文档没有生成任何有效分块")

    return chunks