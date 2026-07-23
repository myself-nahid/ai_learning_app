from pydantic import BaseModel
from typing import List, Dict, Optional, Any

# Screen 1: Dashboard components
class WeeklyStatsSchema(BaseModel):
    lessons_completed: int
    minutes_spent: int
    streak_days: int
    days_active: Dict[str, bool] # For rendering the M T W T F S S circles

class ContinueLearningSchema(BaseModel):
    lesson_id: int
    path_title: str
    lesson_title: str
    progress_percentage: int
    cards_completed: int
    total_cards: int
    minutes_remaining: int
    image_url: str

class PathCardSchema(BaseModel):
    path_id: int
    title: str
    level: str
    total_lessons: int
    total_minutes: int
    progress_percentage: int
    image_url: str

class LearnDashboardResponse(BaseModel):
    weekly_stats: WeeklyStatsSchema
    continue_learning: Optional[ContinueLearningSchema]
    learning_paths: List[PathCardSchema]
    recommended_lessons: List[Any]

# Screen 2: Path Details
class LessonListItemSchema(BaseModel):
    lesson_id: int
    sequence_order: int
    title: str
    description: str
    total_cards: int
    cards_completed: int
    estimated_minutes: int
    status: str # "locked", "in_progress", "completed"

class PathDetailResponse(BaseModel):
    path_id: int
    title: str
    description: str
    level: str
    progress_percentage: int
    lessons: List[LessonListItemSchema]

# Screens 3-8: Lesson Cards
class LessonCardData(BaseModel):
    type: str # "text", "example", "list", "comparison", "quiz"
    content: Any # Dynamic payload based on type
    
class LessonContentResponse(BaseModel):
    lesson_id: int
    title: str
    total_cards: int
    current_card_index: int
    cards: List[LessonCardData]