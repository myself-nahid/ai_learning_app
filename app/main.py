from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

from app.api.v1.endpoints import auth, users, content, quizzes
from app.db.session import engine
from app.db.models import Base
from app.schemas.response import StandardResponse
import os  

if not os.path.exists("uploads"):
    os.makedirs("uploads")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # AUTO-CREATE TABLES ON STARTUP (For easy testing without Alembic yet)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title="AI Learning Platform API",
    version="1.0.0",
    lifespan=lifespan
)

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
app.mount("/static", StaticFiles(directory="uploads"), name="static")

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Learning Platform API"}