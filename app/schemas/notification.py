from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class NotificationSchema(BaseModel):
    id: int
    user_id: int
    title: str
    message: str
    type: Optional[str] = "news"  # 'news', 'pulse', 'quiz', 'system'
    is_read: bool
    created_at: datetime
    # Optional navigation fields for frontend deep-linking
    url: Optional[str] = None
    news_id: Optional[int] = None

    class Config:
        from_attributes = True
