from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.search import router as search_router

from app.api.v1.chat import router as chat_router

from app.api.v1.mcp import router as mcp_router

from app.api.v1.agent import router as agent_router

from app.api.v1.auth import router as auth_router

from app.api.v1.knowledge_bases import (
    router as knowledge_bases_router,
)

from app.api.v1.notes import router as notes_router

from app.api.v1.mcp_registry import (
    router as mcp_registry_router,
)

from app.api.v1.conversations import (
    router as conversations_router,
)

from app.api.v1.reviews import router as reviews_router
from app.api.v1.profile import router as profile_router
from app.api.v1.knowledge_graph import router as knowledge_graph_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(documents_router)
api_router.include_router(search_router)
api_router.include_router(chat_router)
api_router.include_router(mcp_router)
api_router.include_router(mcp_registry_router)
api_router.include_router(agent_router)
api_router.include_router(auth_router)
api_router.include_router(
    knowledge_bases_router
)
api_router.include_router(notes_router)
api_router.include_router(conversations_router)
api_router.include_router(reviews_router)
api_router.include_router(profile_router)
api_router.include_router(knowledge_graph_router)
