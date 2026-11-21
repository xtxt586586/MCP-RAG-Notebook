from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.documents import MAX_FILE_SIZE, upload_document


@pytest.mark.asyncio
async def test_oversized_upload_is_read_with_a_bound_and_rejected() -> None:
    class OversizedFile:
        filename = "oversized.txt"
        read = AsyncMock(return_value=b"x" * (MAX_FILE_SIZE + 1))

    file = OversizedFile()
    with pytest.raises(HTTPException) as exc:
        await upload_document(
            current_user=object(), knowledge_base_id=None, file=file, db=None
        )

    assert exc.value.status_code == 413
    file.read.assert_awaited_once_with(MAX_FILE_SIZE + 1)
