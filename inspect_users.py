import asyncio
# pyrefly: ignore [missing-import]
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.models import User

async def main():
    async with SessionLocal() as db:
        res = await db.execute(select(User))
        users = res.scalars().all()
        print([(u.id, u.email, u.is_superuser, u.role, u.is_verified, u.full_name) for u in users])

asyncio.run(main())

