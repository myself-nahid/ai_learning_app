import asyncio
from app.db.session import engine
from app.db.models import Base
from app.db.init_db import init_db


async def main():
    print("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Initializing database...")
    await init_db()
    print("Database setup completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
