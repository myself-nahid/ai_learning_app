from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import jwt 
from app.db.session import SessionLocal
from app.db.models import User
from app.core.config import settings
from app.core.security import ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the token using PyJWT
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if user_id is None or token_type != "access":
            raise credentials_exception
            
    except jwt.PyJWTError:  
        raise credentials_exception

    # Fetch user from database
    result = await db.execute(select(User).filter(User.id == int(user_id)))
    user = result.scalars().first()
    
    if user is None:
        raise credentials_exception
    return user