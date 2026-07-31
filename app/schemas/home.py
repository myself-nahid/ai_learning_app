from pydantic import BaseModel
from typing import List, Optional, Dict, Any

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
    headline: Optional[str] = None
    summary: Optional[str] = None
    category: str
    tag: Optional[str] = None
    readTime: Optional[str] = None
    read_time_minutes: Optional[int] = None
    publishedTime: Optional[str] = None
    time_ago: Optional[str] = None
    date: Optional[str] = None
    publisher: Optional[str] = None
    publishedDate: Optional[str] = None
    published_date: Optional[str] = None
    originalUrl: Optional[str] = None
    original_url: Optional[str] = None
    imageUrl: Optional[str] = None
    image_url: Optional[str] = None
    isBookmarked: bool = False
    is_bookmarked: bool = False

    class Config:
        extra = "allow"
        from_attributes = True


class NewsArticleSchema(NewsCardSchema):
    content: Optional[List[Any]] = None
    content_blocks: Optional[List[Any]] = None
    keyTakeaways: Optional[List[str]] = None
    key_takeaways: Optional[List[str]] = None
    quote: Optional[Any] = None
    sections: Optional[List[Any]] = None


class HomeDashboardResponse(BaseModel):
    greeting: str
    unread_notifications: int
    profile_image: Optional[str]
    daily_pulse: DailyPulseSchema
    todays_news: List[NewsCardSchema]

    class Config:
        extra = "allow"
        from_attributes = True


class NewsCardResponse(NewsCardSchema):
    class Config:
        extra = "allow"
        from_attributes = True


class NewsDetailResponse(NewsArticleSchema):
    relatedNews: List[NewsCardSchema] = []
    related_news: List[NewsCardSchema] = []

    class Config:
        extra = "allow"
        from_attributes = True