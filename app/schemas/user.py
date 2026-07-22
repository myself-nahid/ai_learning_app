from pydantic import BaseModel, EmailStr
from typing import List, Optional

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
    full_name: str
    difficulty_level: str 
    interests: List[str]