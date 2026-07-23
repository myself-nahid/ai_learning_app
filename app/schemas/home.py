from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class DailyPulseSchema(BaseModel):
    activities_completed: int
    total_activities: int = 5
    progress_percentage: int
    estimated_time_left: str
    check_news: bool
    check_lesson: bool
    check_quiz: bool

class NewsCardSchema(BaseModel):
    id: int
    image_url: str
    tag: str
    headline: str
    summary: str
    read_time_minutes: int
    time_ago: str
    is_bookmarked: bool

class HomeDashboardResponse(BaseModel):
    greeting: str
    unread_notifications: int
    profile_image: Optional[str]
    daily_pulse: DailyPulseSchema
    todays_news: List[NewsCardSchema]

    class Config:
        from_attributes = True

class NewsCardResponse(BaseModel):
    id: int
    image_url: str
    tag: str
    headline: str
    summary: Optional[str] = None
    read_time_minutes: int
    time_ago: str
    is_bookmarked: bool

    class Config:
        from_attributes = True

class NewsDetailResponse(BaseModel):
    id: int
    image_url: str
    tag: str
    headline: str
    published_date: str # e.g., "28 Jun 2026"
    read_time_minutes: int
    time_ago: str
    content_blocks: List[Any]
    is_bookmarked: bool
    related_news: List[NewsCardResponse]