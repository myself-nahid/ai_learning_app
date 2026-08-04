from datetime import datetime
# pyrefly: ignore [missing-import]
from typing import List
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, File, UploadFile, status
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select, func, desc

from app.core.config import settings 
from app.api.deps import get_db, get_current_user
from app.db.models import AppSettings, User, UserProfile
from app.schemas.user import ChangePasswordRequest, UpdateNameRequest, UpdateSettingsRequest, UserOnboarding, UserProfileResponse, RegisterPushTokenRequest
from app.db.models import NewsArticle, UserNewsInteraction, UserProfile
from app.schemas.home import NewsCardSchema 
from app.schemas.user import UpdatePreferencesRequest
from app.schemas.response import (
    ImageUploadResponse,
    LegalPageResponse,
    MessageResponse,
    StatusMessageResponse,
    DeviceRegisterResponse,
)
from app.services.user_service import (
    save_profile_image,
    create_user_profile,
    update_user_settings,
    change_user_password,
    update_user_preferences,
)

router = APIRouter(prefix="/users", tags=["Users & Profile"])

@router.post("/onboarding", status_code=status.HTTP_201_CREATED, response_model=StatusMessageResponse)
async def complete_onboarding(
    data: UserOnboarding,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user) 
):
    # Use the service layer to handle profile creation
    await create_user_profile(
        db=db,
        user_id=current_user.id,
        interests=data.interests,
        ai_level=data.ai_level,
        primary_goal=data.primary_goal,
    )
    
    # Trigger background live news generation for selected interests without blocking onboarding completion HTTP response
    count_res = await db.execute(select(func.count(NewsArticle.id)))
    if (count_res.scalar() or 0) < 10:
        import asyncio
        from app.services.news_service import background_generate_news_task
        asyncio.create_task(background_generate_news_task(data.interests))

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
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # If the user has an image, attach the base URL to it
    if current_user.profile_image:
        if not current_user.profile_image.startswith("http"):
            current_user.profile_image = f"{settings.BASE_URL.rstrip('/')}{current_user.profile_image}"

    # Attach User XP & Badge Info
    from app.services.xp_service import get_user_xp_info
    xp_info = await get_user_xp_info(db, current_user.id)
    for k, v in xp_info.items():
        setattr(current_user, k, v)
            
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
    
    from app.services.xp_service import get_user_xp_info
    xp_info = await get_user_xp_info(db, current_user.id)
    for k, v in xp_info.items():
        setattr(current_user, k, v)
        
    return current_user

# 3. UPLOAD PROFILE IMAGE (Camera icon in UI)
@router.post("/upload-image", response_model=ImageUploadResponse)
async def upload_profile_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Validate and save via service layer
    relative_path = await save_profile_image(file, current_user.id)
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
    # Use the service layer
    return await update_user_settings(
        db=db,
        user=current_user,
        push_notifications=data.push_notifications,
        daily_reminder_time=data.daily_reminder_time,
        fcm_token=data.fcm_token,
    )

# PUBLIC: REGISTER PUSH TOKEN WITHOUT LOGIN
@router.post("/register-push-token")
async def register_push_token_public(
    data: RegisterPushTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Public endpoint to register device push token without login requirement.
    """
    return {"message": "Push token registered successfully", "fcm_token": data.fcm_token}

# 5. CHANGE PASSWORD (Change Password Popup UI)
@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Use the service layer
    await change_user_password(
        db=db,
        user=current_user,
        current_password=data.current_password,
        new_password=data.new_password,
        confirm_password=data.confirm_password,
    )
    return {"message": "Password updated successfully"}

# SAVED ITEMS ENDPOINT
@router.get("/saved", response_model=List[NewsCardSchema])
async def get_saved_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Fetches all news articles that the user has bookmarked.
    Matches the 'Saved' button in the UI.
    """
    query = (
        select(NewsArticle)
        .join(UserNewsInteraction, UserNewsInteraction.news_id == NewsArticle.id)
        .filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.is_bookmarked == True
        )
        .order_by(desc(NewsArticle.published_at))
    )
    
    result = await db.execute(query)
    articles = result.scalars().all()

    from app.api.v1.endpoints.home import get_time_ago_string
    
    saved_list = []
    seen_ids = set()
    for art in articles:
        if art.id in seen_ids:
            continue
        seen_ids.add(art.id)
        date_str = art.published_at.strftime("%d %b %Y") if art.published_at else datetime.utcnow().strftime("%d %b %Y")
        pub_time = get_time_ago_string(art.published_at) if art.published_at else "Just now"
        publisher_val = art.publisher or "TechCrunch"
        original_url_val = art.original_url or "https://techcrunch.com"
        image_url_val = art.image_url or "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=600&auto=format&fit=crop"
        read_time_val = art.read_time_minutes or 3
        read_time_str = f"{read_time_val} min read"
        category_val = art.category or art.tag or "Generative AI"
        tag_val = art.tag or art.category or "Generative AI"

        saved_list.append({
            "id": str(art.id),
            "title": art.headline or "",
            "headline": art.headline or "",
            "summary": art.summary or "",
            "category": category_val,
            "tag": tag_val,
            "readTime": read_time_str,
            "read_time_minutes": read_time_val,
            "publishedTime": pub_time,
            "time_ago": pub_time,
            "date": date_str,
            "publisher": publisher_val,
            "publishedDate": date_str,
            "published_date": date_str,
            "originalUrl": original_url_val,
            "original_url": original_url_val,
            "imageUrl": image_url_val,
            "image_url": image_url_val,
            "isBookmarked": True,
            "is_bookmarked": True
        })
    
    return saved_list


# PREFERENCES ENDPOINT
@router.patch("/preferences", response_model=StatusMessageResponse)
async def update_preferences(
    data: UpdatePreferencesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Updates the user's primary interests or AI level and fetches live news matching selected interests.
    Matches the 'Preferences' button in the UI.
    """
    # Use the service layer
    await update_user_preferences(
        db=db,
        user_id=current_user.id,
        interests=data.interests,
        ai_level=data.ai_level,
        primary_goal=data.primary_goal,
    )
    
    if data.interests and len(data.interests) > 0:
        import asyncio
        from app.services.news_service import background_generate_news_task
        asyncio.create_task(background_generate_news_task(data.interests))

    return {
        "status": "success",
        "message": "Preferences updated successfully. Your feed will reflect these changes.",
    }

@router.get("/legal/terms", response_model=LegalPageResponse)
async def get_terms(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AppSettings).filter(AppSettings.id == 1))
    app_config = res.scalars().first()
    return {
        "title": "Terms and Conditions",
        "content": app_config.terms_conditions if app_config else "Coming soon."
    }

@router.get("/legal/privacy", response_model=LegalPageResponse)
async def get_privacy(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AppSettings).filter(AppSettings.id == 1))
    app_config = res.scalars().first()
    return {
        "title": "Privacy Policy",
        "content": app_config.privacy_policy if app_config else "Coming soon."
    }

class DeviceTokenRequest(BaseModel):
    fcm_token: str
    timezone: str = "UTC"

@router.post("/register-device", response_model=DeviceRegisterResponse)
async def register_device(
    data: DeviceTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.fcm_token = data.fcm_token
    current_user.timezone = data.timezone
    await db.commit()
    return {"message": "Device successfully registered for push notifications"}