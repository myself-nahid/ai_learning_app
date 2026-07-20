from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api.v1.endpoints import auth # The file we made in step 1
from app.db.session import engine
from app.db.models import Base # The models file from step 1

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

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Learning Platform API"}