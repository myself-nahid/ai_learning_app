from datetime import datetime, timedelta
from typing import Any, Union
import jwt
import hashlib  
from passlib.context import CryptContext
from app.core.config import settings

# Configuration
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """
    Pre-hashes password with SHA-256 to handle the 72-character 
    bcrypt limit, then hashes with bcrypt.
    """
    # 1. Convert password to SHA-256 to ensure it's always a fixed length < 72
    prepared_password = hashlib.sha256(password.encode()).hexdigest()
    # 2. Hash with bcrypt
    return pwd_context.hash(prepared_password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Pre-hashes the plain password and compares it to the stored bcrypt hash.
    """
    prepared_password = hashlib.sha256(plain_password.encode()).hexdigest()
    return pwd_context.verify(prepared_password, hashed_password)

def create_access_token(subject: Union[str, Any]) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(subject: Union[str, Any]) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)