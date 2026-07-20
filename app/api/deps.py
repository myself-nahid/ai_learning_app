from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import SessionLocal

async def get_db():
    """Yields a database session and closes it after the request completes."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()