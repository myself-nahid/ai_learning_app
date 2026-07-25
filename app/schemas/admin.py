from pydantic import BaseModel
from typing import List

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