# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
# pyrefly: ignore [missing-import]
from fastapi.staticfiles import StaticFiles
# pyrefly: ignore [missing-import]
from sqlalchemy import text

from app.api.v1.endpoints import auth, users, content, quizzes, home, learn, quiz_tab, daily_briefing, admin, notifications
from app.db.session import engine
from app.db.models import Base
from app.schemas.response import StandardResponse
import os
import logging

from app.core.exceptions import (
    global_exception_handler,
    app_exception_handler,
    http_exception_handler_wrapper,
    AppException,
    StarletteHTTPException,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

if not os.path.exists("uploads"):
    os.makedirs("uploads")

from app.db.session import engine
from app.db.models import Base
from app.db.init_db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # AUTO-CREATE TABLES & SEED DATA ON STARTUP
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_db()
    yield

app = FastAPI(
    title="Tod AI Learning Platform API",
    version="1.0.0",
    lifespan=lifespan
)

# Register exception handlers
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler_wrapper)

# CORS configuration for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, change this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the Authentication Router
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(content.router, prefix="/api/v1")
app.include_router(quizzes.router, prefix="/api/v1")
app.include_router(home.router, prefix="/api/v1")
app.include_router(learn.router, prefix="/api/v1")
app.include_router(quiz_tab.router, prefix="/api/v1")
app.include_router(daily_briefing.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")  
app.include_router(notifications.router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory="uploads"), name="static")

@app.get("/")
async def root():
    return {"message": "Welcome to the Tod-AI Learning Platform API"}