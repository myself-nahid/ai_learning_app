from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.db.models import User, UserProfile
from app.schemas.user import UserOnboarding, UserProfileCreate, UserProfileResponse, UserResponse

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
        full_name=data.full_name,
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