from pydantic import BaseModel, EmailStr
from typing import List, Optional
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
    email: EmailStr
    difficulty_level: str # "beginner", "intermediate", "advanced"
    interests: List[str]  # ["AI", "Blockchain"]

class UserProfileResponse(BaseModel):
    full_name: str
    email: EmailStr
    profile_image: Optional[str]
    push_notifications: bool
    daily_reminder_time: time
    member_since: datetime

    class Config:
        from_attributes = True

class UpdateNameRequest(BaseModel):
    full_name: str

class UpdateSettingsRequest(BaseModel):
    push_notifications: Optional[bool] = None
    daily_reminder_time: Optional[time] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str