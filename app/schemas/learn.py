# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from typing import List, Dict, Optional, Any


class WeeklyStatsSchema(BaseModel):
    lessons_completed: int
    minutes_spent: int
    streak_days: int
    days_active: Dict[str, bool]


class ContinueLearningSchema(BaseModel):
    path_id: int
    lesson_id: int
    title: str
    path_title: str
    completed_cards: int
    total_cards: int
    progress_percentage: Optional[int] = 0
    minutes_remaining: Optional[int] = 5
    image_url: Optional[str] = None


class PathCardSchema(BaseModel):
    path_id: int
    title: str
    level: str
    total_lessons: int
    total_minutes: int
    progress_percentage: int
    image_url: Optional[str] = None


class RecommendedLessonSchema(BaseModel):
    id: int
    path_id: int
    lesson_id: int
    title: str
    description: str
    level: str
    duration: str
    category: str
    image_url: Optional[str] = None


class LearnDashboardResponse(BaseModel):
    weekly_stats: WeeklyStatsSchema
    continue_learning: Optional[ContinueLearningSchema]
    learning_paths: List[PathCardSchema]
    recommended_lessons: List[RecommendedLessonSchema]


class LessonListItemSchema(BaseModel):
    lesson_id: int
    sequence_order: int
    title: str
    description: str
    total_cards: int
    cards_completed: int
    estimated_minutes: int
    status: str


class PathDetailResponse(BaseModel):
    path_id: int
    title: str
    description: str
    level: str
    progress_percentage: int
    lessons: List[LessonListItemSchema]


class LessonContentResponse(BaseModel):
    lesson_id: int
    path_id: Optional[int] = None
    title: str
    estimated_minutes: int
    total_cards: Optional[int] = None
    cards_completed: Optional[int] = None
    cards: List[Any]