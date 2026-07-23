from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

# --- SUB-COMPONENTS ---
class DailyPulseSchema(BaseModel):
    activities_completed: int # e.g., 2
    total_activities: int = 5
    progress_percentage: int # e.g., 40
    estimated_time_left: str # e.g., "5 min left"
    check_news: bool
    check_lesson: bool
    check_quiz: bool

class NewsCardSchema(BaseModel):
    id: int
    image_url: str
    tag: str
    headline: str
    summary: Optional[str]
    read_time_minutes: int
    time_ago: str # e.g., "2 hours ago"
    is_bookmarked: bool

# Screen 1: Home Dashboard
class HomeDashboardResponse(BaseModel):
    greeting: str # e.g., "Good morning, Prayas"
    unread_notifications: int
    profile_image: Optional[str]
    daily_pulse: DailyPulseSchema
    todays_news: List[NewsCardSchema]

# Screen 2: News Detail Page
class NewsDetailResponse(BaseModel):
    id: int
    image_url: str
    tag: str
    headline: str
    date_str: str # e.g., "28 Jun 2026"
    read_time_minutes: int
    time_ago: str
    content_blocks: List[Dict[str, Any]] # Renders Intro, Takeaways, Quotes, etc.
    is_bookmarked: bool
    related_news: List[NewsCardSchema]