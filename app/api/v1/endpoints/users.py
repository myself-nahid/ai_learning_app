from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.db.models import User, UserProfile
from app.schemas.user import UserProfileCreate, UserProfileResponse, UserResponse

router = APIRouter(prefix="/users", tags=["Users & Profile"])

@router.post("/onboarding", response_model=UserProfileResponse)
async def complete_onboarding(
    profile_data: UserProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Check if profile already exists
    result = await db.execute(select(UserProfile).filter(UserProfile.user_id == current_user.id))
    existing_profile = result.scalars().first()
    
    if existing_profile:
        raise HTTPException(status_code=400, detail="User has already completed onboarding. Use PUT to update.")

    # Create new profile
    new_profile = UserProfile(
        user_id=current_user.id,
        full_name=profile_data.full_name,
        difficulty_level=profile_data.difficulty_level,
        interests=profile_data.interests
    )
    
    db.add(new_profile)
    await db.commit()
    await db.refresh(new_profile)
    
    return new_profile

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