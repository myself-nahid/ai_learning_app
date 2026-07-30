"""Service layer for user-related business logic."""

import os
import shutil
import logging
import datetime
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.db.models import User, UserProfile, UserProgress

logger = logging.getLogger(__name__)

# Allowed image extensions for profile uploads
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
# Maximum file size (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


def validate_image_file(file: UploadFile) -> None:
    """Validate uploaded image file extension and size."""
    # Validate file extension
    if "." not in file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has no extension.",
        )

    file_extension = file.filename.rsplit(".", 1)[-1].lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file extension '{file_extension}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Validate file size by reading the content
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to start

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )


async def save_profile_image(file: UploadFile, user_id: int) -> str:
    """Save uploaded profile image and return the relative path."""
    validate_image_file(file)

    UPLOAD_DIR = "uploads/profiles"
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Delete any existing profile image for this user (any extension)
    for existing in os.listdir(UPLOAD_DIR):
        if existing.startswith(f"user_{user_id}."):
            try:
                os.remove(os.path.join(UPLOAD_DIR, existing))
            except OSError:
                pass

    file_extension = file.filename.rsplit(".", 1)[-1].lower()
    file_name = f"user_{user_id}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    # Save the new file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    relative_path = f"/static/profiles/{file_name}"
    return relative_path


async def create_user_profile(
    db: AsyncSession,
    user_id: int,
    interests: list,
    ai_level: str,
    primary_goal: str,
) -> UserProfile:
    """Create a new user profile and initialize progress tracking."""
    # Check if profile already exists — if so, update (upsert) instead of erroring
    profile_query = await db.execute(
        select(UserProfile).filter(UserProfile.user_id == user_id)
    )
    existing_profile = profile_query.scalars().first()
    if existing_profile:
        existing_profile.interests = interests
        existing_profile.ai_level = ai_level
        existing_profile.primary_goal = primary_goal
        return existing_profile

    # Create User Profile
    new_profile = UserProfile(
        user_id=user_id,
        interests=interests,
        ai_level=ai_level,
        primary_goal=primary_goal,
    )

    # Initialize Gamification Progress
    new_progress = UserProgress(
        user_id=user_id,
        current_xp=0,
        current_streak=0,
        longest_streak=0,
    )

    db.add(new_profile)
    db.add(new_progress)

    return new_profile


async def update_user_settings(
    db: AsyncSession,
    user: User,
    push_notifications: Optional[bool] = None,
    daily_reminder_time=None,
    fcm_token: Optional[str] = None,
) -> User:
    """Update user notification and reminder settings."""
    if push_notifications is not None:
        user.push_notifications = push_notifications
    if daily_reminder_time is not None:
        if isinstance(daily_reminder_time, str):
            try:
                parts = [int(p) for p in daily_reminder_time.split(":")]
                user.daily_reminder_time = datetime.time(*parts)
            except Exception:
                pass
        else:
            user.daily_reminder_time = daily_reminder_time
    if fcm_token is not None:
        user.fcm_token = fcm_token

    await db.commit()
    await db.refresh(user)
    return user


async def change_user_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> None:
    """Change user password after verifying current password."""
    if not verify_password(current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if new_password != confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New passwords do not match",
        )

    user.hashed_password = get_password_hash(new_password)
    await db.commit()


async def update_user_preferences(
    db: AsyncSession,
    user_id: int,
    interests: Optional[list] = None,
    ai_level: Optional[str] = None,
    primary_goal: Optional[str] = None,
) -> UserProfile:
    """Update user interests, AI level, or primary goal."""
    result = await db.execute(
        select(UserProfile).filter(UserProfile.user_id == user_id)
    )
    profile = result.scalars().first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Please complete onboarding first.",
        )

    if interests is not None:
        profile.interests = interests
    if ai_level:
        profile.ai_level = ai_level
    if primary_goal:
        profile.primary_goal = primary_goal

    await db.commit()
    return profile
