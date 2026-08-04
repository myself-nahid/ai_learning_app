# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Union
from datetime import time, datetime

class UserProfileCreate(BaseModel):
    full_name: str
    difficulty_level: str  # e.g., "beginner", "intermediate", "advanced"
    interests: List[str]   # e.g., ["Technology", "Space", "History"]

class UserProfileResponse(UserProfileCreate):
    id: int
    user_id: int

    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    id: int
    email: str
    is_verified: bool
    profile: Optional[UserProfileResponse] = None

    class Config:
        from_attributes = True

class UserOnboarding(BaseModel):
    interests: List[str] 
    ai_level: str
    primary_goal: str

# class OnboardingSchema(BaseModel):
#     primary_interest: str = Field(..., pattern="^(General AI|Business & Leadership|Consulting & Strategy|Finance & Banking|Marketing, Design & Content|Technology & Innovation|Science)$")
#     ai_level: str = Field(..., pattern="^(Beginner|Intermediate|Advanced)$")
#     # Field from Vision Doc (often a hidden or secondary screen)
#     primary_goal: Optional[str] = "Stay informed about AI"

class UserProfileResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    profile_image: Optional[str]
    push_notifications: bool
    daily_reminder_time: time
    member_since: datetime
    
    # XP & Badge System
    current_xp: Optional[int] = 0
    badge_name: Optional[str] = "AI Novice"
    badge_level: Optional[str] = "Tier 1"
    badge_icon: Optional[str] = "✨"
    badge_color: Optional[str] = "#06B6D4"
    next_badge_xp: Optional[int] = 100
    progress_percentage: Optional[int] = 0

    class Config:
        from_attributes = True

class UpdateNameRequest(BaseModel):
    full_name: str

class UpdateSettingsRequest(BaseModel):
    push_notifications: Optional[bool] = None
    daily_reminder_time: Optional[Union[time, str]] = None
    fcm_token: Optional[str] = None

class RegisterPushTokenRequest(BaseModel):
    fcm_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

class UpdatePreferencesRequest(BaseModel):
    interests: Optional[List[str]] = None
    ai_level: Optional[str] = None
    primary_goal: Optional[str] = None