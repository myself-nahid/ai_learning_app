from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.core.config import settings 
from app.api.deps import get_db, get_current_user
from app.core.security import get_password_hash, verify_password
from app.db.models import User, UserProfile, UserProgress
from app.schemas.user import ChangePasswordRequest, UpdateNameRequest, UpdateSettingsRequest, UserOnboarding, UserProfileCreate, UserProfileResponse, UserResponse
import os
import shutil

router = APIRouter(prefix="/users", tags=["Users & Profile"])

@router.post("/onboarding", status_code=status.HTTP_201_CREATED)
async def complete_onboarding(
    data: UserOnboarding,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user) 
):
    # 1. Check if profile already exists
    profile_query = await db.execute(select(UserProfile).filter(UserProfile.user_id == current_user.id))
    if profile_query.scalars().first():
        raise HTTPException(status_code=400, detail="Onboarding already completed")

    # 2. Create User Profile
    new_profile = UserProfile(
        user_id=current_user.id,
        primary_interest=data.primary_interest,
        ai_level=data.ai_level,
        primary_goal=data.primary_goal
    )
    
    # 3. Initialize Gamification Progress
    new_progress = UserProgress(
        user_id=current_user.id,
        current_xp=0,
        current_streak=0,
        longest_streak=0
    )

    db.add(new_profile)
    db.add(new_progress)
    
    await db.commit()
    
    return {
        "status": "success",
        "message": "Personalized feed ready! Welcome to TodAI."
    }

# @router.get("/me", response_model=UserResponse)
# async def get_my_profile(
#     current_user: User = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db)
# ):
#     # Fetch user along with their profile using selectinload
#     result = await db.execute(
#         select(User).options(selectinload(User.profile)).filter(User.id == current_user.id)
#     )
#     user_with_profile = result.scalars().first()
    
#     return user_with_profile

# 1. GET PROFILE INFORMATION (Account Info UI)
@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    # If the user has an image, attach the base URL to it
    if current_user.profile_image:
        if not current_user.profile_image.startswith("http"):
            current_user.profile_image = f"{settings.BASE_URL.rstrip('/')}{current_user.profile_image}"
            
    return current_user

# 2. UPDATE FULL NAME (Edit Profile UI)
@router.patch("/update-name", response_model=UserProfileResponse)
async def update_name(
    data: UpdateNameRequest, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.full_name = data.full_name
    await db.commit()
    await db.refresh(current_user)
    return current_user

# 3. UPLOAD PROFILE IMAGE (Camera icon in UI)
@router.post("/upload-image")
async def upload_profile_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    UPLOAD_DIR = "uploads/profiles"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    file_extension = file.filename.split(".")[-1]
    file_name = f"user_{current_user.id}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # 1. Save the relative path in the database
    relative_path = f"/static/profiles/{file_name}"
    current_user.profile_image = relative_path
    
    await db.commit()
    await db.refresh(current_user)

    # 2. Construct the FULL readable URL using .env settings
    # We use .rstrip("/") to ensure there are no double slashes like "http://url.com//static"
    full_url = f"{settings.BASE_URL.rstrip('/')}{relative_path}"
    
    return {"image_url": full_url}

# 4. UPDATE NOTIFICATION & REMINDER (Daily Reminder UI)
@router.patch("/update-settings", response_model=UserProfileResponse)
async def update_settings(
    data: UpdateSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if data.push_notifications is not None:
        current_user.push_notifications = data.push_notifications
    if data.daily_reminder_time is not None:
        current_user.daily_reminder_time = data.daily_reminder_time
        
    await db.commit()
    await db.refresh(current_user)
    return current_user

# 5. CHANGE PASSWORD (Change Password Popup UI)
@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify current password
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    # Confirm new passwords match
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="New passwords do not match")

    current_user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    return {"message": "Password updated successfully"}

@router.get("/legal/terms")
async def get_terms():
    return {
        "title": "Terms and Condition",
        "content": "1. Acceptance of Terms... 2. User Accounts... 3. Use of Application..."
    }

@router.get("/legal/privacy")
async def get_privacy():
    return {
        "title": "Privacy Policy",
        "content": "1. Information We Collect... 1.1 Account Information... 1.2 Learning Data..."
    }

from pydantic import BaseModel

class DeviceTokenRequest(BaseModel):
    fcm_token: str
    timezone: str = "UTC"

@router.post("/register-device")
async def register_device(
    data: DeviceTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.fcm_token = data.fcm_token
    current_user.timezone = data.timezone
    await db.commit()
    return {"message": "Device successfully registered for push notifications"}