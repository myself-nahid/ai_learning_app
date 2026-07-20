from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import jwt

from app.api.deps import get_db 
from app.core.security import (
    get_password_hash, verify_password, 
    create_access_token, create_refresh_token, SECRET_KEY, ALGORITHM
)
from app.db.models import User, OTP
from app.schemas.auth import UserCreate, Token, OTPVerify, ForgotPassword, ResetPassword
from app.services.email_service import generate_and_save_otp, send_otp_email
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["Authentication"])

# 1. SIGNUP & SEND OTP
@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).filter(User.email == user_in.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create unverified user
    new_user = User(email=user_in.email, hashed_password=get_password_hash(user_in.password))
    db.add(new_user)
    
    # Generate OTP
    otp_code = await generate_and_save_otp(db, user_in.email, purpose="signup")
    await send_otp_email(user_in.email, otp_code, purpose="Signup Verification")
    
    return {"message": "User created. Please verify your email with the OTP sent."}

# 2. VERIFY OTP (For Signup)
@router.post("/verify-otp")
async def verify_otp(data: OTPVerify, db: AsyncSession = Depends(get_db)):
    # Find OTP
    result = await db.execute(
        select(OTP).filter(OTP.email == data.email, OTP.otp_code == data.otp_code, OTP.purpose == "signup")
    )
    otp_record = result.scalars().first()

    if not otp_record or otp_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    # Update User
    user_result = await db.execute(select(User).filter(User.email == data.email))
    user = user_result.scalars().first()
    user.is_verified = True
    
    # Delete used OTP
    await db.delete(otp_record)
    await db.commit()

    return {"message": "Email successfully verified. You can now login."}

# 3. RESEND OTP
@router.post("/resend-otp")
async def resend_otp(data: ForgotPassword, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.email == data.email))
    if not user_result.scalars().first():
        raise HTTPException(status_code=404, detail="User not found")

    otp_code = await generate_and_save_otp(db, data.email, purpose="signup")
    await send_otp_email(data.email, otp_code, purpose="Signup Verification")
    
    return {"message": "A new OTP has been sent to your email."}

# 4. LOGIN (Returns Access + Refresh Token)
@router.post("/login", response_model=Token)
async def login(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).filter(User.email == user_in.email))
    user = result.scalars().first()

    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email first")

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer"
    }

# 5. REFRESH TOKEN
@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_token: str):
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
            
        user_id = payload.get("sub")
        return {
            "access_token": create_access_token(user_id),
            "refresh_token": refresh_token, # Return the same refresh token or rotate it
            "token_type": "bearer"
        }
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

# 6. FORGOT PASSWORD (Send OTP)
@router.post("/forgot-password")
async def forgot_password(data: ForgotPassword, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.email == data.email))
    if not user_result.scalars().first():
        # Return standard message to prevent email enumeration attacks
        return {"message": "If that email exists, a reset OTP has been sent."}

    otp_code = await generate_and_save_otp(db, data.email, purpose="reset_password")
    await send_otp_email(data.email, otp_code, purpose="Password Reset")
    
    return {"message": "If that email exists, a reset OTP has been sent."}

# 7. RESET PASSWORD (Validate OTP & Change Password)
@router.post("/reset-password")
async def reset_password(data: ResetPassword, db: AsyncSession = Depends(get_db)):
    # Find valid OTP
    result = await db.execute(
        select(OTP).filter(OTP.email == data.email, OTP.otp_code == data.otp_code, OTP.purpose == "reset_password")
    )
    otp_record = result.scalars().first()

    if not otp_record or otp_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    # Update Password
    user_result = await db.execute(select(User).filter(User.email == data.email))
    user = user_result.scalars().first()
    
    user.hashed_password = get_password_hash(data.new_password)
    await db.delete(otp_record) # Remove used OTP
    await db.commit()

    return {"message": "Password successfully reset. You can now login."}