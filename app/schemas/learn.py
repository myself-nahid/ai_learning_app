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
    # Authored lesson quiz (QuizSet id) when this lesson has one — Daily Pulse routes here
    quiz_set_id: Optional[int] = None


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
    source_type: Optional[str] = "curriculum"
    lessons: List[LessonListItemSchema]
    # Daily plan (default mode): the server serves the user's next sequential
    # window of lessons (max 5) instead of the whole 20-30-lesson path.
    daily_mode: bool = False
    daily_start_order: Optional[int] = None
    daily_lesson_ids: List[int] = []
    path_total_lessons: int = 0
    path_completed_lessons: int = 0
    path_progress_percentage: int = 0


class LessonContentResponse(BaseModel):
    lesson_id: int
    path_id: Optional[int] = None
    quiz_set_id: Optional[int] = None
    title: str
    estimated_minutes: int
    total_cards: Optional[int] = None
    cards_completed: Optional[int] = None
    cards: List[Any]