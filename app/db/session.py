from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

engine = create_async_engine(
    settings.ASYNC_DATABASE_URI, 
    echo=False, # Set to True if you want to see SQL queries in the console
    future=True
)

# Async session factory
SessionLocal = async_sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)