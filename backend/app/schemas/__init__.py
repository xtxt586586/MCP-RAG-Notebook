from app.schemas.auth import (
    AgentMemorySettingsRequest,
    AgentMemorySettingsResponse,
    LoginRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)

from app.schemas.note import NoteCreate, NoteResponse

from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)

from app.schemas.mcp_server import (
    MCPServerCreate,
    MCPServerResponse,
    MCPServerUpdate,
)

__all__ = [
    "LoginRequest",
    "AgentMemorySettingsRequest",
    "AgentMemorySettingsResponse",
    "PasswordChangeRequest",
    "ProfileUpdateRequest",
    "RefreshTokenRequest",
    "RegisterRequest",
    "TokenResponse",
    "UserResponse",
    "KnowledgeBaseCreate",
    "KnowledgeBaseResponse",
    "KnowledgeBaseUpdate",
    "NoteCreate",
    "NoteResponse",
    "ConversationResponse",
    "ConversationDetailResponse",
    "MessageResponse",
    "MCPServerCreate",
    "MCPServerResponse",
    "MCPServerUpdate",
]
