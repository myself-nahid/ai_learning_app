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