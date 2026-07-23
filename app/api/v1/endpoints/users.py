from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.core.security import get_password_hash, verify_password
from app.db.models import User, UserProfile
from app.schemas.user import ChangePasswordRequest, UpdateNameRequest, UpdateSettingsRequest, UserOnboarding, UserProfileCreate, UserProfileResponse, UserResponse
import os
import shutil

router = APIRouter(prefix="/users", tags=["Users & Profile"])

@router.post("/onboarding")
async def complete_onboarding(
    data: UserOnboarding,
    db: AsyncSession = Depends(get_db)
):
    # 1. Find user by email
    result = await db.execute(
        select(User).options(selectinload(User.profile)).filter(User.email == data.email)
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Security Check: Ensure they are verified before onboarding
    if not user.is_verified:
        raise HTTPException(
            status_code=403, 
            detail="Email not verified. Please verify your email first."
        )

    # 3. Check if profile already exists
    if user.profile:
        raise HTTPException(status_code=400, detail="Onboarding already completed.")

    # 4. Create the profile
    new_profile = UserProfile(
        user_id=user.id,
        # full_name=data.full_name,
        difficulty_level=data.difficulty_level,
        interests=data.interests
    )
    
    db.add(new_profile)
    await db.commit()
    
    return {"message": "Onboarding complete! You can now log in to your account."}

@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Fetch user along with their profile using selectinload
    result = await db.execute(
        select(User).options(selectinload(User.profile)).filter(User.id == current_user.id)
    )
    user_with_profile = result.scalars().first()
    
    return user_with_profile

# 1. GET PROFILE INFORMATION (Account Info UI)
@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
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
    # Standard production path logic
    UPLOAD_DIR = "uploads/profiles"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    file_extension = file.filename.split(".")[-1]
    file_name = f"user_{current_user.id}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    current_user.profile_image = f"/static/profiles/{file_name}"
    await db.commit()
    return {"image_url": current_user.profile_image}

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