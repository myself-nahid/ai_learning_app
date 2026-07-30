from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class StandardResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Any] = None

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """Simple response with just a message field."""
    message: str


class StatusMessageResponse(BaseModel):
    """Response with status and message fields."""
    status: str
    message: str


class ImageUploadResponse(BaseModel):
    """Response for image upload endpoints."""
    image_url: str


class BookmarkToggleResponse(BaseModel):
    """Response for bookmark toggle endpoint."""
    is_bookmarked: bool


class ReadStatusResponse(BaseModel):
    """Response for mark-as-read endpoint."""
    message: str
    pulse_updated: bool


class TriggerPulseResponse(BaseModel):
    """Response for trigger-daily-pulse endpoint."""
    status: str
    message: str


class DailyLessonResponse(BaseModel):
    """Response for daily lesson endpoint."""
    title: Optional[str]
    content_blocks: Optional[Any]
    practical_takeaway: Optional[str]


class LegalPageResponse(BaseModel):
    """Response for legal pages (terms/privacy)."""
    title: str
    content: str


class DeviceRegisterResponse(BaseModel):
    """Response for device registration endpoint."""
    message: str


class ProgressSaveResponse(BaseModel):
    """Response for progress save endpoint."""
    status: str


class LessonCompleteRequest(BaseModel):
    lesson_id: int
    completed_cards: int
    minutes_spent: int


class LessonCompleteResponse(BaseModel):
    """Response for lesson complete endpoint."""
    message: str
    streak_updated: bool
    pulse_updated: bool


class SuspendActionResponse(BaseModel):
    """Response for user suspend/unsuspend action."""
    message: str
