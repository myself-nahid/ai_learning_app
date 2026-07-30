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
    id: str
    title: str
    summary: Optional[str] = None
    category: str
    readTime: str
    publishedTime: str
    date: str
    publisher: Optional[str] = None
    publishedDate: Optional[str] = None
    originalUrl: Optional[str] = None
    imageUrl: Optional[str] = None
    isBookmarked: bool


class NewsArticleSchema(NewsCardSchema):
    content: Optional[List[Any]] = None
    keyTakeaways: Optional[List[str]] = None
    quote: Optional[str] = None
    sections: Optional[List[Any]] = None


class HomeDashboardResponse(BaseModel):
    greeting: str
    unread_notifications: int
    profile_image: Optional[str]
    daily_pulse: DailyPulseSchema
    todays_news: List[NewsCardSchema]

    class Config:
        from_attributes = True


class NewsCardResponse(NewsCardSchema):
    class Config:
        from_attributes = True


class NewsDetailResponse(NewsArticleSchema):
    relatedNews: List[NewsCardSchema] = []