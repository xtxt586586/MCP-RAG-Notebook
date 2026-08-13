from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.search import router as search_router

from app.api.v1.chat import router as chat_router

from app.api.v1.mcp import router as mcp_router

from app.api.v1.agent import router as agent_router
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(documents_router)
api_router.include_router(search_router)
api_router.include_router(chat_router)
api_router.include_router(mcp_router)
api_router.include_router(agent_router)