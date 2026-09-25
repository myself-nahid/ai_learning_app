# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr
from typing import List, Optional

class KpiCard(BaseModel):
    value: int
    trend_percentage: int
    trend_type: str # "up" or "down"
    trend_text: str # e.g., "vs last week"

class ChartDataPoint(BaseModel):
    day: str # e.g., "Mon", "Tue"
    count: int

class ActivityLogItem(BaseModel):
    id: int
    action_type: str
    description: str
    time_ago: str

class AdminDashboardResponse(BaseModel):
    # Top KPIs
    total_users: KpiCard
    active_users: KpiCard
    new_users: KpiCard
    suspended_users: KpiCard
    
    # Charts
    user_registrations_chart: List[ChartDataPoint]
    daily_active_users_chart: List[ChartDataPoint]
    
    # Feed
    recent_activity: List[ActivityLogItem]

# LIST VIEW SCHEMAS 
class AdminUserListItem(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    ai_level: str
    interest: str
    joined_date: str # e.g. "20 Jul 2026"
    status: str # "Active" or "Suspended"

class AdminUserListResponse(BaseModel):
    total_accounts: int
    users: List[AdminUserListItem]

# DETAIL VIEW SCHEMAS 
class AdminUserDetailStats(BaseModel):
    learning_streak: str # e.g. "14 days"
    lessons_completed: int
    quizzes_completed: int
    avg_quiz_score: str # e.g. "78%"
    total_learning_time: str # e.g. "34h 20m"

class AdminUserDetailResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    ai_level: str
    interest: str
    joined_date: str
    last_active: str
    status: str
    stats: AdminUserDetailStats

# ACTION SCHEMAS 
class SuspendUserRequest(BaseModel):
    suspend: bool # True to suspend, False to reactivate

# ADMIN PROFILE SCHEMAS 
class AdminProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None # Will hash this if provided


class AdminProfileResponse(BaseModel):
    full_name: str
    email: str
    profile_image: Optional[str]

# APP SETTINGS SCHEMAS 
class AppSettingsSchema(BaseModel):
    support_email: str
    privacy_policy: str
    terms_conditions: str
    account_deletion_policy: str

class AppSettingsUpdate(BaseModel):
    support_email: Optional[str] = None
    privacy_policy: Optional[str] = None
    terms_conditions: Optional[str] = None
    account_deletion_policy: Optional[str] = None


# ── CURRICULUM MANAGEMENT SCHEMAS ──────────────────────────────────────────

class CurriculumLessonItem(BaseModel):
    lesson_id: int
    path_id: int
    sequence_order: int
    title: str
    description: Optional[str] = None
    learning_goal: Optional[str] = None
    estimated_minutes: int
    cards_data: List[dict]


class CurriculumPathItem(BaseModel):
    path_id: int
    title: str
    description: Optional[str] = None
    level: str
    total_lessons: int
    total_minutes: int
    curriculum_slug: Optional[str] = None
    lessons: List[CurriculumLessonItem]


class CurriculumListResponse(BaseModel):
    total_paths: int
    total_lessons: int
    paths: List[CurriculumPathItem]


class LessonCreateRequest(BaseModel):
    path_id: int
    sequence_order: int
    title: str
    description: Optional[str] = None
    learning_goal: Optional[str] = None
    estimated_minutes: int = 5
    cards_data: List[dict]


class LessonUpdateRequest(BaseModel):
    sequence_order: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    learning_goal: Optional[str] = None
    estimated_minutes: Optional[int] = None
    cards_data: Optional[List[dict]] = None


class PathCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    level: str = "Beginner"


class PathUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    level: Optional[str] = None


class CurriculumImportResponse(BaseModel):
    message: str
    paths_upserted: int
    lessons_upserted: int


# ── AI TOPIC CURRICULUM (CONTENT REVIEW) SCHEMAS ─────────────────────────

class AiTopicCreate(BaseModel):
    """Payload for creating a new AI curriculum topic."""
    slug: str
    title: str
    description: str
    level: str
    category: str
    sequence_order: int
    search_keywords: List[str] = []
    learning_objectives: List[str] = []
    is_active: bool = True


class AiTopicUpdate(BaseModel):
    """Payload for fully editing an existing AI curriculum topic.
    All fields optional; None means "leave unchanged"."""
    slug: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    level: Optional[str] = None
    category: Optional[str] = None
    sequence_order: Optional[int] = None
    search_keywords: Optional[List[str]] = None
    learning_objectives: Optional[List[str]] = None
    is_active: Optional[bool] = None


class AiTopicDetailResponse(BaseModel):
    """Full topic detail (every editable field) for the admin content review UI."""
    id: int
    slug: str
    title: str
    description: str
    level: str
    category: str
    sequence_order: int
    search_keywords: List[str]
    learning_objectives: List[str]
    is_active: bool
    created_at: Optional[str] = None
    coverage: Optional[dict] = None
    learning_path_id: Optional[int] = None


class AiTopicActionResponse(BaseModel):
    """Response after create/update/delete/toggle on an AI curriculum topic."""
    message: str
    id: Optional[int] = None
    slug: Optional[str] = None
    title: Optional[str] = None
    is_active: Optional[bool] = None
    deleted: Optional[bool] = None
    deleted_progress_rows: Optional[int] = None
    deleted_learning_path: Optional[bool] = None