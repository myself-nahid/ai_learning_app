from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload 
import jwt
from datetime import datetime

from app.api.deps import get_current_user, get_db 
from app.core.security import (
    get_password_hash, verify_password, 
    create_access_token, create_refresh_token, SECRET_KEY, ALGORITHM
)
from app.db.models import User, OTP, UserProfile 
from app.schemas.auth import UserCreate, Token, OTPVerify, ForgotPassword, ResetPassword, UserLogin
from app.schemas.response import StandardResponse
from app.services.email_service import generate_and_save_otp, send_otp_email

router = APIRouter(prefix="/auth", tags=["Authentication"])

# 1. SIGNUP & SEND OTP (Real-time with BackgroundTasks)
@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=StandardResponse)
async def signup(
    user_in: UserCreate, 
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).filter(User.email == user_in.email))
    existing_user = result.scalars().first()

    if existing_user:
        if existing_user.is_verified:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # If user exists but not verified, update their name and password
        existing_user.full_name = user_in.full_name
        existing_user.hashed_password = get_password_hash(user_in.password)
        target_user = existing_user
    else:
        # Create new user with full_name
        target_user = User(
            full_name=user_in.full_name, # Added this
            email=user_in.email, 
            hashed_password=get_password_hash(user_in.password),
            is_verified=False
        )
        db.add(target_user)
    
    await db.commit()

    # Generate and send OTP (Real-time email)
    otp_code = await generate_and_save_otp(db, user_in.email, purpose="signup")
    background_tasks.add_task(send_otp_email, email=user_in.email, otp_code=otp_code, purpose="Signup Verification")
    
    return StandardResponse(
        success=True,
        message="Signup successful! Verification code sent to your email."
    )

# 2. VERIFY OTP (Now returns Tokens!)
@router.post("/verify-otp", response_model=StandardResponse)
async def verify_otp(data: OTPVerify, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OTP).filter(OTP.email == data.email, OTP.otp_code == data.otp_code, OTP.purpose == "signup")
    )
    otp_record = result.scalars().first()

    if not otp_record or otp_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    # Fetch User with Profile to check onboarding status
    user_result = await db.execute(
        select(User).options(selectinload(User.profile)).filter(User.email == data.email)
    )
    user = user_result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    user.is_verified = True
    
    extracted_user_id = user.id
    extracted_is_onboarded = user.profile is not None
    
    await db.delete(otp_record)
    await db.commit() # Objects expire here, but we don't care anymore!

    return StandardResponse(
        success=True,
        message="Email verified successfully!",
        data={
            "access_token": create_access_token(extracted_user_id),
            "refresh_token": create_refresh_token(extracted_user_id),
            "token_type": "bearer",
            "is_onboarded": extracted_is_onboarded
        }
    )

# 3. RESEND OTP
@router.post("/resend-otp", response_model=StandardResponse)
async def resend_otp(
    data: ForgotPassword, 
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db)
):
    user_result = await db.execute(select(User).filter(User.email == data.email))
    if not user_result.scalars().first():
        raise HTTPException(status_code=404, detail="User not found")

    otp_code = await generate_and_save_otp(db, data.email, purpose="signup")
    
    background_tasks.add_task(
        send_otp_email, 
        email=data.email, 
        otp_code=otp_code, 
        purpose="Signup Verification"
    )
    
    return StandardResponse(
        success=True,
        message="A new OTP has been sent to your email.",
        data=None
    )

# 4. LOGIN (No longer blocked by Onboarding)
@router.post("/login", response_model=StandardResponse)
async def login(user_in: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).options(selectinload(User.profile)).filter(User.email == user_in.email)
    )
    user = result.scalars().first()

    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email first")

    return StandardResponse(
        success=True,
        message="Login successful!",
        data={
            "access_token": create_access_token(user.id),
            "refresh_token": create_refresh_token(user.id),
            "token_type": "bearer",
            "is_onboarded": user.profile is not None
        }
    )

# 5. REFRESH TOKEN (Using PyJWTError)
@router.post("/refresh", response_model=StandardResponse)
async def refresh_token(refresh_token: str):
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
            
        user_id = payload.get("sub")
        return StandardResponse(
            success=True,
            message="Token refreshed successfully!",
            data={
                "access_token": create_access_token(user_id),
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "is_onboarded": False
            }
        )
    except jwt.PyJWTError: # Updated for PyJWT
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

# 6. FORGOT PASSWORD
@router.post("/forgot-password", response_model=StandardResponse)
async def forgot_password(
    data: ForgotPassword, 
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db)
):
    user_result = await db.execute(select(User).filter(User.email == data.email))
    if not user_result.scalars().first():
        return StandardResponse(
            success=True,
            message="If that email exists, a reset OTP has been sent.",
            data=None
        )

    otp_code = await generate_and_save_otp(db, data.email, purpose="reset_password")
    
    background_tasks.add_task(
        send_otp_email, 
        email=data.email, 
        otp_code=otp_code, 
        purpose="Password Reset"
    )
    
    return StandardResponse(
        success=True,
        message="If that email exists, a reset OTP has been sent.",
        data=None
    )

# 7. RESET PASSWORD
@router.post("/reset-password")
async def reset_password(data: ResetPassword, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OTP).filter(OTP.email == data.email, OTP.otp_code == data.otp_code, OTP.purpose == "reset_password")
    )
    otp_record = result.scalars().first()

    if not otp_record or otp_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    user_result = await db.execute(select(User).filter(User.email == data.email))
    user = user_result.scalars().first()
    
    user.hashed_password = get_password_hash(data.new_password)
    await db.delete(otp_record)
    await db.commit()

    return StandardResponse(
        success=True,
        message="Password successfully reset. You can now login."
    )

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Successfully logged out"}