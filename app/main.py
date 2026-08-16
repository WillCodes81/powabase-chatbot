from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.rate_limit import limiter
from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.credits import router as credits_router
from app.routes.ingest import router as ingest_router
from app.routes.sessions import router as sessions_router
from app.routes.tools import router as tools_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(chatbots_router)
    app.include_router(sessions_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    app.include_router(tools_router)
    app.include_router(credits_router)
    return app


app = create_app()
