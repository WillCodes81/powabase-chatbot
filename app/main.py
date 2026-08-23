from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.applications import Starlette
from starlette.routing import Mount

from app.rate_limit import limiter
from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.credits import router as credits_router
from app.routes.ingest import router as ingest_router
from app.routes.public import router as public_router
from app.routes.sessions import router as sessions_router
from app.routes.tools import router as tools_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://ec2-3-128-189-163.us-east-2.compute.amazonaws.com",],
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


def create_public_app() -> FastAPI:
    """
    A fully separate FastAPI app for /public/* -- not a router mounted onto
    the main app. Starlette middleware wraps the whole ASGI app it's added
    to, including anything mounted beneath it, and intercepts CORS
    preflight before routing even runs -- so a second CORSMiddleware on a
    sub-router mounted under `app` would still be gated by `app`'s own
    restrictive origin list first. Two independent FastAPI apps, dispatched
    by a bare Starlette router with no middleware of its own (see `app`
    below), is the only way to give /public/* a genuinely independent CORS
    policy without touching main_app's.
    """
    public_app = FastAPI(title="Powabase RAG Chatbot -- Public Sharing", version="1.0.0")

    public_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    public_app.state.limiter = limiter
    public_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    public_app.add_middleware(SlowAPIMiddleware)

    public_app.include_router(public_router)
    return public_app


main_app = create_app()
public_app = create_public_app()

# Order matters: /public must be matched before the catch-all "/" mount.
app = Starlette(routes=[
    Mount("/public", app=public_app),
    Mount("/", app=main_app),
])
