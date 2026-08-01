import asyncio
import json
import sys

# pyrefly: ignore [missing-import]
import httpx
# pyrefly: ignore [missing-import]
from sqlalchemy import select
import sys
from pathlib import Path

# Ensure project root is on sys.path so `app` imports work when running this script
proj_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(proj_root))

from app.db.session import SessionLocal
from app.db.models import User
from app.core.security import create_access_token

async def main():
    async with SessionLocal() as db:
        res = await db.execute(select(User).filter(User.is_verified==True))
        user = res.scalars().first()
        if not user:
            print('No verified user found in DB. Please create a user via /api/v1/auth/signup and verify OTP.')
            return
        token = create_access_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.get('http://localhost:8000/api/v1/home/dashboard', headers=headers)
                print('STATUS', r.status_code)
                try:
                    print(json.dumps(r.json(), indent=2))
                except Exception:
                    print(r.text)
            except Exception as e:
                print('Request failed:', e)

if __name__ == '__main__':
    asyncio.run(main())
