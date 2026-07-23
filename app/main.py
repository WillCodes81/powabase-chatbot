from fastapi import FastAPI

from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.ingest import router as ingest_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")
    app.include_router(auth_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    return app


app = create_app()

